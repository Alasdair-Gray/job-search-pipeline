#!/usr/bin/env python3
"""
Job Search Pipeline — Stage 1: Scrape
======================================
Uses JobSpy to scrape LinkedIn (primary), Indeed, and Glassdoor.
Runs a separate search for each job title × location combination
defined in pipeline_config.json.

Cross-platform duplicates (same role advertised on multiple boards)
are removed using rapidfuzz fuzzy matching on title + company before
the results are handed to ingest.py.

Output JSON uses field names that match pipeline_config.json field_mapping,
so ingest.py requires no changes.

Usage:
    python3 scrape.py            # live scrape
    python3 scrape.py --dry-run  # skips scraping, uses most recent raw_scrape_*.json

Requirements (install once):
    pip3 install python-jobspy rapidfuzz pandas --break-system-packages
"""

import json
import sys
import hashlib
import pandas as pd
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
CONFIG_F = BASE_DIR / "pipeline_config.json"
LOG_FILE = BASE_DIR / "ingest_log.txt"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def load_config() -> dict:
    return json.loads(CONFIG_F.read_text())


def make_job_id(url: str) -> str:
    """Generate a stable 12-char job_id from the job URL."""
    return hashlib.md5(url.encode()).hexdigest()[:12]


def safe_str(val) -> str:
    """Convert a value to string, returning '' for NaN/None."""
    try:
        if pd.isna(val):
            return ""
    except (TypeError, ValueError):
        pass
    return str(val) if val is not None else ""


def format_salary(row) -> str:
    """
    Convert JobSpy salary fields (min_amount, max_amount, currency, interval)
    into a human-readable string that ingest.py's parse_salary_gbp() can handle.
    Returns '' if no salary data.
    """
    min_amt  = row.get("min_amount")
    max_amt  = row.get("max_amount")
    currency = safe_str(row.get("currency")) or "GBP"
    interval = safe_str(row.get("interval")) or "yearly"

    has_min = min_amt is not None and not (isinstance(min_amt, float) and pd.isna(min_amt))
    has_max = max_amt is not None and not (isinstance(max_amt, float) and pd.isna(max_amt))

    if not has_min and not has_max:
        return ""

    symbol = "£" if currency.upper() in ("GBP", "£") else (
             "$" if currency.upper() in ("USD", "$") else currency
    )

    if has_min and has_max:
        return f"{symbol}{int(min_amt):,} - {symbol}{int(max_amt):,} per {interval}"
    elif has_min:
        return f"from {symbol}{int(min_amt):,} per {interval}"
    else:
        return f"up to {symbol}{int(max_amt):,} per {interval}"


def format_location(row) -> str:
    """
    Build a location string from JobSpy's location column.
    JobSpy may return a Location namedtuple, a dict, or a plain string.
    Falls back to separate city/state/country columns if present.
    """
    loc = row.get("location")

    # Namedtuple (Location object)
    if hasattr(loc, "city"):
        parts = [p for p in [loc.city, loc.state, loc.country] if p]
        location_str = ", ".join(parts)

    # Dict
    elif isinstance(loc, dict):
        parts = [loc.get("city"), loc.get("state"), loc.get("country")]
        location_str = ", ".join(p for p in parts if p)

    # Plain string
    elif loc and safe_str(loc):
        location_str = safe_str(loc)

    # Fall back to separate columns (older JobSpy versions)
    else:
        parts = [safe_str(row.get(c)) for c in ("city", "state", "country") if safe_str(row.get(c))]
        location_str = ", ".join(parts)

    # Append remote flag
    is_remote = row.get("is_remote")
    try:
        remote = bool(is_remote) and not pd.isna(is_remote)
    except (TypeError, ValueError):
        remote = False

    if remote:
        return f"{location_str} (Remote)" if location_str else "Remote"
    return location_str or ""


def format_date(val) -> str:
    """Convert a date/datetime/string to ISO 8601 string."""
    if val is None:
        return ""
    try:
        if pd.isna(val):
            return ""
    except (TypeError, ValueError):
        pass
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return safe_str(val)


# ---------------------------------------------------------------------------
# Deduplication (cross-platform fuzzy match)
# ---------------------------------------------------------------------------

def normalise_key(text: str) -> str:
    return str(text or "").lower().strip()


def deduplicate(jobs: list, threshold: int = 88) -> list:
    """
    Remove cross-platform duplicates using fuzzy matching on
    (title + company). When duplicates are found, the LinkedIn
    record is preferred; otherwise the first-seen record is kept.

    threshold=88 catches "Director of Product Management" vs
    "Director, Product Management" but avoids false positives
    between different roles at the same company.
    """
    from rapidfuzz import fuzz

    if not jobs:
        return jobs

    kept = []

    for job in jobs:
        key = normalise_key(job["title"]) + " " + normalise_key(job["company"])
        duplicate_idx = None

        for i, kept_job in enumerate(kept):
            kept_key = normalise_key(kept_job["title"]) + " " + normalise_key(kept_job["company"])
            if fuzz.token_sort_ratio(key, kept_key) >= threshold:
                duplicate_idx = i
                break

        if duplicate_idx is None:
            kept.append(job)
        else:
            # Prefer LinkedIn source over others
            if job.get("source") == "linkedin" and kept[duplicate_idx].get("source") != "linkedin":
                kept[duplicate_idx] = job

    return kept


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def scrape_all(config: dict) -> list:
    """
    Run JobSpy for each (job_title × location) combination from config.
    Returns a flat list of job dicts using ingest.py-compatible field names.
    """
    from jobspy import scrape_jobs

    sp         = config["search_params"]
    job_titles = sp.get("job_titles", [sp.get("keywords", "product manager")])
    locations  = sp.get("locations", ["London"])
    hours_old  = sp.get("posted_within_hours", 24)

    all_jobs  = []
    seen_urls = set()
    total_raw = 0

    for title in job_titles:
        for location in locations:
            log(f"  Searching: '{title}' in '{location}'")
            try:
                df = scrape_jobs(
                    site_name                  = ["linkedin"],
                    search_term                = title,
                    location                   = location,
                    hours_old                  = hours_old,
                    results_wanted             = 15,      # per search combination (5 titles × 2 locations = up to 150 total)
                    description_format         = "markdown",
                    linkedin_fetch_description = True,    # fetch full description for each LinkedIn job
                    country_indeed             = "UK",
                    verbose                    = 0,
                )
            except Exception as e:
                log(f"  ERROR scraping '{title}' in '{location}': {e}")
                continue

            if df is None or df.empty:
                log(f"  No results for '{title}' in '{location}'")
                continue

            log(f"  Got {len(df)} results")
            total_raw += len(df)

            for _, row in df.iterrows():
                url = safe_str(row.get("job_url"))
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)

                # Map JobSpy fields → names already in pipeline_config field_mapping
                job = {
                    # identity (field_mapping: ["id", "jobId", "job_id"])
                    "id":              make_job_id(url),

                    # core fields
                    "title":           safe_str(row.get("title")),
                    "company":         safe_str(row.get("company")),
                    "location":        format_location(row),
                    "salary":          format_salary(row),

                    # description (field_mapping: ["descriptionText", "description", ...])
                    "descriptionText": safe_str(row.get("description")),

                    # url (field_mapping: ["jobUrl", "url", "applyUrl"])
                    "jobUrl":          url,

                    # date (field_mapping: ["postedAt", "datePosted", "publishedAt"])
                    "datePosted":      format_date(row.get("date_posted")),

                    # classification
                    "industry":        safe_str(row.get("company_industry")),  # LinkedIn + Indeed only
                    "employmentType":  safe_str(row.get("job_type")),
                    "seniorityLevel":  safe_str(row.get("job_level")),         # LinkedIn only

                    # metadata
                    "source":          safe_str(row.get("site")),
                }
                all_jobs.append(job)

    log(f"Total scraped across all searches (pre-dedup by URL): {total_raw}")
    log(f"Unique URLs: {len(all_jobs)}")
    return all_jobs


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def scrape() -> Path:
    config   = load_config()
    log("=== Stage 1: Scrape (JobSpy) ===")
    log(f"Job titles: {config['search_params'].get('job_titles', [])}")
    log(f"Locations:  {config['search_params'].get('locations', [])}")
    log(f"Hours old:  {config['search_params'].get('posted_within_hours', 24)}")

    raw_jobs = scrape_all(config)
    deduped  = deduplicate(raw_jobs)
    removed  = len(raw_jobs) - len(deduped)

    log(f"Cross-platform dedup removed {removed} duplicate(s) → {len(deduped)} jobs remaining")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path  = BASE_DIR / f"raw_scrape_{timestamp}.json"
    out_path.write_text(json.dumps(deduped, indent=2, ensure_ascii=False))
    log(f"Saved to {out_path.name}")
    return out_path


def dry_run() -> Path:
    """Use the most recent raw_scrape_*.json instead of live scraping."""
    files = sorted(BASE_DIR.glob("raw_scrape_*.json"))
    if not files:
        print("No raw_scrape_*.json files found. Run without --dry-run first.")
        sys.exit(1)
    path = files[-1]
    log(f"=== Stage 1: Dry-run — using {path.name} ===")
    return path


if __name__ == "__main__":
    sys.path.insert(0, str(BASE_DIR))
    import ingest

    if "--dry-run" in sys.argv:
        raw_path = dry_run()
    else:
        raw_path = scrape()

    log("=== Stage 2: Ingest ===")
    ingest.run(raw_path)
    log("Pipeline Stage 1→2 complete.")
