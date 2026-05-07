#!/usr/bin/env python3
"""
Job Search Pipeline — Stage 3: LLM Scoring Engine
===================================================
Reads all jobs with status="new" from jobs_db.csv, scores each one
against Alasdair's profile using the Claude API, and writes scores back.

Usage:
    python score.py

Requires:
    ANTHROPIC_API_KEY set in environment or in a .env file alongside this script.

Output:
    - jobs_db.csv:          score_* columns populated, status → "scored"
    - score_rationales.json: per-dimension rationale text, keyed by job_id
    - score_log.txt:         timestamped run log
"""

import json
import csv
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import anthropic

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR         = Path(__file__).parent
CONFIG_PATH      = BASE_DIR / "pipeline_config.json"
JOBS_DB          = BASE_DIR / "jobs_db.csv"
RATIONALES_FILE  = BASE_DIR / "score_rationales.json"
LOG_FILE         = BASE_DIR / "score_log.txt"
CV_DB_PATH       = (
    BASE_DIR.parent
    / "Job app CV builder"
    / "Job app CV builder tech files"
    / "cv_master_database.json"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_env():
    """Load ANTHROPIC_API_KEY from a .env file if not already in environment."""
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line.startswith("ANTHROPIC_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if key:
                        os.environ["ANTHROPIC_API_KEY"] = key
                        return


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_cv_db() -> dict:
    if not CV_DB_PATH.exists():
        raise FileNotFoundError(f"CV database not found at {CV_DB_PATH}")
    with open(CV_DB_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_rationales() -> dict:
    if RATIONALES_FILE.exists():
        with open(RATIONALES_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_rationales(rationales: dict):
    with open(RATIONALES_FILE, "w", encoding="utf-8") as f:
        json.dump(rationales, f, indent=2)


def log(message: str):
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {message}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ---------------------------------------------------------------------------
# Profile builder
# ---------------------------------------------------------------------------

def build_profile(cv_db: dict) -> dict:
    """
    Extract a concise candidate profile from the CV database.
    Returns skills, domains, roles, and a brief background summary.
    """
    skills   = set()
    domains  = set()
    keywords = set()
    roles    = []

    for entry in cv_db.get("entries", []):
        skills.update(entry.get("skills") or [])
        domains.update(entry.get("domains") or [])
        keywords.update(entry.get("keywords") or [])

        if entry.get("entry_type") == "role_context":
            job = entry.get("job", {})
            roles.append(
                f"{job.get('title', '?')} at {job.get('company', '?')} "
                f"({job.get('dates', '?')})"
            )

    return {
        "skills":   sorted(skills),
        "domains":  sorted(domains),
        "keywords": sorted(keywords),
        "roles":    roles,
    }


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

SCORING_PROMPT = """You are a talent matching expert. Score this job opportunity against the candidate profile below.

CANDIDATE PROFILE:
Name: Alasdair Gray
Seniority: Principal Product Manager / Product Director (~8 years PM experience)
Target roles: Head of Product, Principal PM, Senior PM, Group PM, Lead PM
Target salary: £120,000+ per year
Recent roles: {roles}
Core skills: {skills}
Domains of expertise: {domains}
Preferred industries: B2B SaaS, healthtech, AI/technology, government digital services
Avoid: fintech, pure financial services

JOB TO EVALUATE:
Title: {title}
Company: {company}
Location: {location}
Salary: {salary}
Industry: {industry}
LinkedIn seniority level: {seniority}

JOB DESCRIPTION:
{description}

SCORING TASK:
Score the job on each dimension from 0–10. Be honest and discriminating — reserve 9–10 for exceptional fits.

Dimensions:
1. score_skills ({w_skills}% weight): Match between role's required skills/experience and candidate's demonstrated skills
2. score_seniority ({w_seniority}% weight): Match between role's seniority expectations and Principal PM / Head of Product level
3. score_industry ({w_industry}% weight): Industry fit — B2B SaaS/healthtech/AI/gov = high; unrelated sectors = mid; pure fintech = low
4. score_salary ({w_salary}% weight): Salary alignment with £120k+ target (score 5 if not specified, 8–10 if £150k+)

Respond with ONLY this JSON — no preamble, no markdown:
{{
  "score_skills": <0-10>,
  "score_seniority": <0-10>,
  "score_industry": <0-10>,
  "score_salary": <0-10>,
  "rationale_skills": "<1-2 sentences>",
  "rationale_seniority": "<1-2 sentences>",
  "rationale_industry": "<1-2 sentences>",
  "rationale_salary": "<1-2 sentences>"
}}"""


def call_claude(client: anthropic.Anthropic, prompt: str, model: str) -> dict:
    """Call Claude and return parsed JSON response. Retries once on failure."""
    for attempt in range(2):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=600,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            # Strip any accidental markdown fences
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            return json.loads(text)
        except (json.JSONDecodeError, anthropic.APIError) as e:
            if attempt == 0:
                log(f"  Retrying after error: {e}")
                continue
            raise


def score_job(client: anthropic.Anthropic, job: dict, profile: dict, config: dict) -> dict:
    """Score a single job. Returns scores dict including weighted overall."""
    w = config["scoring_weights"]

    prompt = SCORING_PROMPT.format(
        roles     = "; ".join(profile["roles"][:5]),
        skills    = ", ".join(profile["skills"][:30]),
        domains   = ", ".join(profile["domains"]),
        title     = job.get("title", ""),
        company   = job.get("company", ""),
        location  = job.get("location", ""),
        salary    = job.get("salary_raw") or "Not specified",
        industry  = job.get("industry", ""),
        seniority = job.get("seniority", ""),
        description = (job.get("description") or "")[:3000],
        w_skills    = int(w["skills"]    * 100),
        w_seniority = int(w["seniority"] * 100),
        w_industry  = int(w["industry"]  * 100),
        w_salary    = int(w["salary"]    * 100),
    )

    result = call_claude(client, prompt, config["scoring_model"])

    # Weighted overall (0–100)
    overall = (
        result["score_skills"]    * w["skills"]    +
        result["score_seniority"] * w["seniority"] +
        result["score_industry"]  * w["industry"]  +
        result["score_salary"]    * w["salary"]
    ) * 10

    result["score_overall"] = round(overall, 1)
    return result


# ---------------------------------------------------------------------------
# DB read / write
# ---------------------------------------------------------------------------

def read_db() -> list[dict]:
    if not JOBS_DB.exists():
        return []
    with open(JOBS_DB, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_db(rows: list[dict]):
    if not rows:
        return
    fieldnames = rows[0].keys()
    with open(JOBS_DB, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run():
    load_env()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print(
            "\nERROR: ANTHROPIC_API_KEY not set.\n"
            "Add it to a .env file in the pipeline folder:\n"
            "  ANTHROPIC_API_KEY=sk-ant-...\n"
            "Or export it in your shell before running this script.\n"
        )
        sys.exit(1)

    config  = load_config()
    cv_db   = load_cv_db()
    profile = build_profile(cv_db)
    client  = anthropic.Anthropic(api_key=api_key)

    rows = read_db()
    new_rows = [r for r in rows if r.get("status") == "new"]

    if not new_rows:
        log("No new jobs to score.")
        return

    log(f"=== Scoring run started — {len(new_rows)} new jobs ===")

    rationales = load_rationales()
    scored = 0
    failed = 0

    for row in rows:
        if row.get("status") != "new":
            continue

        job_id = row["job_id"]
        label  = f"{row['title']} @ {row['company']}"
        log(f"  Scoring: {label}")

        try:
            result = score_job(client, row, profile, config)

            # Write scores into the row
            row["score_overall"]   = result["score_overall"]
            row["score_skills"]    = result["score_skills"]
            row["score_seniority"] = result["score_seniority"]
            row["score_industry"]  = result["score_industry"]
            row["score_salary"]    = result["score_salary"]
            row["status"]          = "scored"

            # Store rationale separately
            rationales[job_id] = {
                "skills":    result.get("rationale_skills", ""),
                "seniority": result.get("rationale_seniority", ""),
                "industry":  result.get("rationale_industry", ""),
                "salary":    result.get("rationale_salary", ""),
                "scored_at": datetime.now(timezone.utc).isoformat(),
            }

            log(
                f"    Overall: {result['score_overall']}/100  "
                f"(skills:{result['score_skills']} "
                f"seniority:{result['score_seniority']} "
                f"industry:{result['score_industry']} "
                f"salary:{result['score_salary']})"
            )
            scored += 1

        except Exception as e:
            log(f"  ERROR scoring {label}: {e}")
            row["status"] = "score_failed"
            failed += 1

    write_db(rows)
    save_rationales(rationales)

    log(f"=== Done — scored: {scored} | failed: {failed} ===")
    print(f"\n{scored} job(s) scored. See jobs_db.csv and score_rationales.json for results.")


if __name__ == "__main__":
    run()
