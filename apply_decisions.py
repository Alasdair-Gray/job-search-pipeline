#!/usr/bin/env python3
"""
Job Search Pipeline — Apply Decisions
======================================
Reads a decisions JSON string (copied from review.html) and updates
job statuses and review notes in jobs_db.csv.

Usage (paste from review.html):
    python3 apply_decisions.py '<json_string>'

Or interactively (prompts for paste):
    python3 apply_decisions.py
"""

import csv, json, sys
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent
JOBS_DB  = BASE_DIR / "jobs_db.csv"
LOG_FILE = BASE_DIR / "ingest_log.txt"

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def apply(decisions_json: str):
    try:
        decisions = json.loads(decisions_json)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON — {e}")
        sys.exit(1)

    if not JOBS_DB.exists():
        print(f"Error: {JOBS_DB} not found")
        sys.exit(1)

    rows = list(csv.DictReader(open(JOBS_DB, encoding="utf-8")))
    updated = 0

    for row in rows:
        job_id = row["job_id"]
        if job_id in decisions:
            d = decisions[job_id]
            old_status = row["status"]
            row["status"]       = d.get("status", row["status"])
            row["review_notes"] = d.get("notes", "")
            log(f"  {job_id}: {old_status} → {row['status']}"
                + (f' ("{row["review_notes"]}")' if row["review_notes"] else ""))
            updated += 1

    if updated == 0:
        print("No matching job IDs found — nothing updated.")
        return

    fields = list(rows[0].keys())
    with open(JOBS_DB, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    log(f"Applied {updated} decision(s) to {JOBS_DB.name}")
    print(f"\n✓ {updated} decision(s) saved to jobs_db.csv")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        apply(sys.argv[1])
    else:
        print("Paste your decisions JSON from review.html, then press Enter twice:")
        lines = []
        while True:
            line = input()
            if line == "" and lines and lines[-1] == "":
                break
            lines.append(line)
        apply("\n".join(lines))
