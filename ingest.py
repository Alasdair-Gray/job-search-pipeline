#!/usr/bin/env python3
"""
Job Search Pipeline — Stage 2: Filter & Ingest
================================================
Takes raw Apify openclaw output (JSON), applies hard filters,
deduplicates against the existing jobs_db.csv, and appends new jobs.

Usage:
    python ingest.py <path_to_openclaw_output.json>

Output:
    - Appends passing jobs to jobs_db.csv
    - Writes a log entry to ingest_log.txt
"""

import json
import csv
import re
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR    = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "pipeline_config.json"
JOBS_DB     = BASE_DIR / "jobs_db.csv"
LOG_FILE    = BASE_DIR / "ingest_log.txt"

# ---------------------------------------------------------------------------
# Schema — column order for jobs_db.csv
# ---------------------------------------------------------------------------
DB_COLUMNS = [
    "job_id", "title", "company", "location",
    "salary_raw", "salary_min_gbp", "salary_max_gbp",
    "description", "url", "posted_at", "scraped_at",
    "industry", "employment_type", "seniority",
    "status",
    "score_overall", "score_skills", "score_seniority",
    "score_industry", "score_salary",
    "review_notes",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def get_field(job: dict, *keys):
    """Return the first non-empty value found in job for the given keys."""
    for key in keys:
        val = job.get(key)
        if val is not None and val != "":
            return val
    return ""


def resolve_fields(job: dict, field_name: str, config: dict):
    """Look up field candidates from config field_mapping and return first match."""
    candidates = config.get("field_mapping", {}).get(field_name, [field_name])
    return get_field(job, *candidates)


def load_existing_ids() -> set:
    """Return set of job_ids already stored in jobs_db.csv."""
    if not JOBS_DB.exists():
        return set()
    with open(JOBS_DB, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return {row["job_id"] for row in reader if row.get("job_id")}


def append_to_db(jobs: list):
    """Append a list of normalised job dicts to jobs_db.csv."""
    file_exists = JOBS_DB.exists()
    with open(JOBS_DB, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=DB_COLUMNS, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        writer.writerows(jobs)


def log(message: str):
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {message}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ---------------------------------------------------------------------------
# Salary parsing
# ---------------------------------------------------------------------------

def parse_salary_gbp(salary_str: str):
    """
    Parse a salary string into (min_gbp, max_gbp).
    Returns (None, None) if no salary info present.

    Handles formats like:
        £120,000 - £150,000 per year
        £60-£80k
        $140,000
        55 per hour
    """
    if not salary_str:
        return None, None

    s = str(salary_str).lower().replace(",", "")

    # Extract all numeric values
    numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", s)]
    if not numbers:
        return None, None

    # Discard numbers that are clearly not salary amounts (< 10)
    numbers = [n for n in numbers if n >= 10]
    if not numbers:
        return None, None

    # Annualise if needed
    if "hour" in s or "/hr" in s or "p/h" in s:
        numbers = [n * 2080 for n in numbers]   # 40 hrs * 52 weeks
    elif "day" in s or "/day" in s or "p/d" in s:
        numbers = [n * 260 for n in numbers]    # 5 days * 52 weeks
    elif "month" in s:
        numbers = [n * 12 for n in numbers]

    # Handle "k" shorthand (e.g. "80k")
    if "k" in s:
        numbers = [n * 1000 if n < 1000 else n for n in numbers]

    # Very rough USD→GBP conversion if $ detected and no £
    if "$" in s and "£" not in s:
        numbers = [n * 0.80 for n in numbers]

    if len(numbers) == 1:
        return int(numbers[0]), int(numbers[0])
    return int(min(numbers)), int(max(numbers))


# ---------------------------------------------------------------------------
# Filter functions  (return True = EXCLUDE this job)
# ---------------------------------------------------------------------------

def filter_recency(job: dict, config: dict) -> bool:
    """Exclude if posted more than max_age_hours ago."""
    max_age = config["filters"]["max_age_hours"]
    posted_at = (
        job.get("postedAt")
        or job.get("datePosted")
        or job.get("publishedAt")
        or ""
    )
    if not posted_at:
        return False   # No date info — keep

    now = datetime.now(timezone.utc)
    s   = str(posted_at).lower().strip()

    # Try ISO 8601 timestamp
    try:
        dt = datetime.fromisoformat(s.replace("z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (now - dt) > timedelta(hours=max_age)
    except (ValueError, AttributeError):
        pass

    # Try relative strings: "2 hours ago", "1 day ago", "3 days ago", etc.
    if any(x in s for x in ("just now", "moment", "second")):
        return False
    if "minute" in s:
        return False
    if "hour" in s:
        m = re.search(r"(\d+)\s+hour", s)
        hours = int(m.group(1)) if m else 1
        return hours > max_age
    if "day" in s:
        m = re.search(r"(\d+)\s+day", s)
        days = int(m.group(1)) if m else 1
        return days > (max_age / 24)
    if any(x in s for x in ("week", "month", "year")):
        return True

    return False   # Unknown format — keep


def filter_salary(job: dict, config: dict) -> bool:
    """Exclude only when salary IS provided and maximum is below threshold."""
    min_threshold = config["filters"]["min_salary_gbp"]
    salary_raw = (
        job.get("salary")
        or job.get("salaryRange")
        or job.get("compensation")
        or ""
    )
    if not salary_raw:
        return False   # No salary info — keep

    _, salary_max = parse_salary_gbp(str(salary_raw))
    if salary_max is None:
        return False   # Couldn't parse — keep

    return salary_max < min_threshold


def filter_industry(job: dict, config: dict) -> bool:
    """Exclude if job is in fintech / financial services."""
    industry_keywords  = [k.lower() for k in config["filters"]["exclude_industries"]]
    desc_keywords      = [k.lower() for k in config["filters"]["exclude_industry_description_keywords"]]

    # Check the industries field
    industries = job.get("industries") or job.get("industry") or ""
    if isinstance(industries, list):
        industries_str = " ".join(industries).lower()
    else:
        industries_str = str(industries).lower()

    for kw in industry_keywords:
        if kw in industries_str:
            return True

    # Check first 600 chars of description + company name for strong fintech signals
    desc    = str(job.get("descriptionText") or job.get("description") or "")[:600].lower()
    company = str(job.get("company") or job.get("companyName") or "").lower()
    combined = f"{company} {desc}"

    for kw in desc_keywords:
        if kw in combined:
            return True

    return False


# Keywords that must appear in a job title for it to be considered a PM role.
# Checked as substrings (lowercased). Add more here if relevant roles are missed.
PM_TITLE_KEYWORDS = [
    "product manager",
    "product owner",
    "product management",
    "product director",
    "product lead",
    "head of product",
    "chief product",
    "vp product",
    "vp, product",
    "vice president product",
    "director of product",
    "director, product",
]

# Location strings that indicate a non-UK role. Jobs whose location contains
# one of these (and no UK indicator) are excluded.
NON_UK_LOCATIONS = [
    "united states", " usa", "u.s.a", "canada", "australia", "new zealand",
    "germany", "france", "brazil", "argentina", "colombia", "mexico",
    "india", "singapore", "japan", "china", "dubai", "abu dhabi", "uae",
    "netherlands", "sweden", "norway", "denmark", "finland", "poland",
    "spain", "italy", "portugal", "switzerland", "austria", "belgium",
    "south africa", "nigeria", "kenya", "turkey", "israel",
    # US state patterns that appear in "City, ST" format
    ", al", ", ak", ", az", ", ar", ", ca", ", co", ", ct", ", de",
    ", fl", ", ga", ", hi", ", id", ", il", ", in", ", ia", ", ks",
    ", ky", ", la", ", me", ", md", ", ma", ", mi", ", mn", ", ms",
    ", mo", ", mt", ", ne", ", nv", ", nh", ", nj", ", nm", ", ny",
    ", nc", ", nd", ", oh", ", ok", ", or", ", pa", ", ri", ", sc",
    ", sd", ", tn", ", tx", ", ut", ", vt", ", va", ", wa", ", wv",
    ", wi", ", wy",
]

UK_LOCATION_INDICATORS = [
    "london", "united kingdom", " uk", "uk,", "(uk)", "england", "wales",
    "scotland", "northern ireland", "manchester", "birmingham", "bristol",
    "edinburgh", "leeds", "sheffield", "liverpool", "cambridge", "oxford",
    "reading", "brighton", "guildford", " gb", "gb,",
]


def filter_title_relevance(job: dict) -> bool:
    """
    Exclude if the job title contains no product management keywords.
    Returns True (exclude) if no PM keyword is found.
    """
    title = str(job.get("title") or job.get("jobTitle") or "").lower()
    return not any(kw in title for kw in PM_TITLE_KEYWORDS)


def filter_location(job: dict) -> bool:
    """
    Exclude if the job has a non-empty location that:
      - contains a known non-UK country/state indicator, AND
      - contains no UK indicator.
    Empty locations and "Remote" without country info are kept.
    """
    location = str(job.get("location") or job.get("jobLocation") or "").lower().strip()

    if not location or "remote" in location or "hybrid" in location:
        return False  # Keep — no location info, or explicitly remote/hybrid

    # If a UK indicator is present, always keep
    if any(ind in location for ind in UK_LOCATION_INDICATORS):
        return False

    # If a non-UK indicator is present, exclude
    if any(ind in location for ind in NON_UK_LOCATIONS):
        return True

    return False  # Unknown location — keep


def filter_seniority(job: dict, config: dict) -> bool:
    """
    Exclude if the description explicitly requires FEWER years of PM experience
    than our minimum. We only exclude when evidence is clear — ambiguous = keep.
    """
    min_years = config["filters"]["min_years_pm_experience"]
    desc = str(job.get("descriptionText") or job.get("description") or "").lower()

    patterns = [
        r"(\d+)\+?\s*years?\s+(?:of\s+)?(?:product\s+management|product\s+manager|pm)\s+experience",
        r"(\d+)\+?\s*years?\s+experience\s+(?:in|as)\s+(?:a\s+)?(?:product\s+manager|product\s+management)",
        r"minimum\s+(?:of\s+)?(\d+)\s+years?\s+(?:of\s+)?(?:product|pm)",
        r"at\s+least\s+(\d+)\s+years?\s+(?:of\s+)?(?:product|pm)",
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, desc):
            required = int(match.group(1))
            if required < min_years:
                return True   # Explicitly requires too few years

    return False


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def normalise(job: dict, config: dict) -> dict:
    """Map a raw openclaw job object to the jobs_db schema."""
    salary_raw = str(resolve_fields(job, "salary", config))
    salary_min, salary_max = parse_salary_gbp(salary_raw)

    industries = resolve_fields(job, "industries", config)
    if isinstance(industries, list):
        industries = ", ".join(industries)

    description = str(resolve_fields(job, "description", config))
    # Flatten newlines for CSV storage
    description = description.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")

    return {
        "job_id":        str(resolve_fields(job, "job_id", config)),
        "title":         str(resolve_fields(job, "title", config)),
        "company":       str(resolve_fields(job, "company", config)),
        "location":      str(resolve_fields(job, "location", config)),
        "salary_raw":    salary_raw,
        "salary_min_gbp": salary_min if salary_min is not None else "",
        "salary_max_gbp": salary_max if salary_max is not None else "",
        "description":   description,
        "url":           str(resolve_fields(job, "url", config)),
        "posted_at":     str(resolve_fields(job, "posted_at", config)),
        "scraped_at":    datetime.now(timezone.utc).isoformat(),
        "industry":      str(industries),
        "employment_type": str(resolve_fields(job, "employment_type", config)),
        "seniority":     str(resolve_fields(job, "seniority", config)),
        "status":        "new",
        "score_overall": "",
        "score_skills":  "",
        "score_seniority": "",
        "score_industry": "",
        "score_salary":  "",
        "review_notes":  "",
    }


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(input_path: str):
    config       = load_config()
    existing_ids = load_existing_ids()

    with open(input_path, encoding="utf-8") as f:
        raw = json.load(f)

    # openclaw may wrap output in {"items": [...]}
    if isinstance(raw, dict):
        raw = raw.get("items") or raw.get("results") or raw.get("data") or []

    log(f"=== Ingest run started — {len(raw)} jobs loaded from {input_path} ===")

    counts = {
        "total":              len(raw),
        "passed":             0,
        "skipped_duplicate":  0,
        "skipped_title":      0,
        "skipped_location":   0,
        "skipped_recency":    0,
        "skipped_salary":     0,
        "skipped_industry":   0,
        "skipped_seniority":  0,
    }

    new_jobs = []

    for job in raw:
        # Resolve job_id using field mapping
        job_id = str(resolve_fields(job, "job_id", config))
        title  = str(job.get("title") or job.get("jobTitle") or "Unknown title")
        co     = str(job.get("company") or job.get("companyName") or "Unknown company")
        label  = f"{title} @ {co}"

        # Deduplicate
        if job_id and job_id in existing_ids:
            counts["skipped_duplicate"] += 1
            continue

        # --- Hard filters ---
        if filter_title_relevance(job):
            counts["skipped_title"] += 1
            log(f"  [TITLE]     {label}")
            continue

        if filter_location(job):
            counts["skipped_location"] += 1
            loc = job.get("location") or job.get("jobLocation") or "?"
            log(f"  [LOCATION]  {label}  (location: {loc})")
            continue

        if filter_recency(job, config):
            counts["skipped_recency"] += 1
            log(f"  [RECENCY]   {label}")
            continue

        if filter_salary(job, config):
            counts["skipped_salary"] += 1
            sal = job.get("salary") or job.get("salaryRange") or "?"
            log(f"  [SALARY]    {label}  (salary: {sal})")
            continue

        if filter_industry(job, config):
            counts["skipped_industry"] += 1
            log(f"  [INDUSTRY]  {label}")
            continue

        if filter_seniority(job, config):
            counts["skipped_seniority"] += 1
            log(f"  [SENIORITY] {label}")
            continue

        # Passed all filters
        new_jobs.append(normalise(job, config))
        existing_ids.add(job_id)
        counts["passed"] += 1
        log(f"  [PASSED]    {label}")

    if new_jobs:
        append_to_db(new_jobs)

    log(
        f"=== Done — passed: {counts['passed']} | "
        f"duplicates: {counts['skipped_duplicate']} | "
        f"title: {counts['skipped_title']} | "
        f"location: {counts['skipped_location']} | "
        f"recency: {counts['skipped_recency']} | "
        f"salary: {counts['skipped_salary']} | "
        f"industry: {counts['skipped_industry']} | "
        f"seniority: {counts['skipped_seniority']} ==="
    )

    return counts


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python ingest.py <path_to_openclaw_output.json>")
        sys.exit(1)
    results = run(sys.argv[1])
    print(f"\nResult: {results['passed']} new jobs added to jobs_db.csv")
