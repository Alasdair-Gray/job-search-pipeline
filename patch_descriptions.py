#!/usr/bin/env python3
"""
patch_descriptions.py
=====================
One-off script to backfill missing LinkedIn job descriptions into jobs_db.csv.

The May 2026 scrape ran without linkedin_fetch_description=True, so all
LinkedIn results came back with empty descriptions. This script fetches
each description individually using JobSpy's own LinkedIn session
(same headers and cookie logic it uses during normal scraping).

Usage (run from Mac terminal with venv active):
    python3 patch_descriptions.py

Safe to re-run — jobs that already have a description are skipped.
"""

import csv
import time
import random
from pathlib import Path

BASE_DIR = Path(__file__).parent
JOBS_CSV = BASE_DIR / "jobs_db.csv"


def build_session():
    """Spin up a JobSpy LinkedIn session using the correct class name and model."""
    from jobspy.linkedin import LinkedIn
    from jobspy.model import ScraperInput, Site, Country

    scraper_input = ScraperInput(
        site_type=[Site.LINKEDIN],
        search_term="product manager",
        country=Country.UK,
        linkedin_fetch_description=True,
        results_wanted=1,
    )
    scraper = LinkedIn(scraper_input)
    return scraper.session


def fetch_description(session, job_url: str) -> str:
    """
    Fetch a single LinkedIn job description using the shared session.
    Returns plain text, or '' on failure.
    """
    from bs4 import BeautifulSoup
    try:
        resp = session.get(job_url, timeout=15)
        if resp.status_code != 200:
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")
        div = soup.find("div", class_=lambda c: c and "show-more-less-html__markup" in c)
        if not div:
            return ""
        text = div.get_text(separator=" ", strip=True)
        return text
    except Exception as e:
        print(f"    Error: {e}")
        return ""


def main():
    if not JOBS_CSV.exists():
        print("jobs_db.csv not found. Run scrape.py first.")
        return

    with open(JOBS_CSV, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    to_patch = [
        r for r in rows
        if "linkedin.com" in r.get("url", "")
        and not r.get("description", "").strip()
    ]

    print(f"Total jobs in DB:           {len(rows)}")
    print(f"LinkedIn jobs missing desc: {len(to_patch)}")

    if not to_patch:
        print("Nothing to patch — all LinkedIn jobs already have descriptions.")
        return

    print("\nBuilding LinkedIn session…")
    session = build_session()
    print("Session ready. Fetching descriptions…\n")

    url_to_row = {r["url"]: r for r in rows}
    patched = 0
    failed  = 0

    for i, row in enumerate(to_patch, 1):
        url = row["url"]
        print(f"  [{i}/{len(to_patch)}] {row['title']} @ {row['company']}")

        desc = fetch_description(session, url)
        if desc:
            # Flatten newlines — same treatment as ingest.py
            desc = desc.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
            url_to_row[url]["description"] = desc
            patched += 1
            print(f"    ✓ {len(desc)} chars")
        else:
            failed += 1
            print(f"    ✗ No description (listing may have expired)")

        # Polite delay to avoid rate-limiting
        if i < len(to_patch):
            time.sleep(random.uniform(1.5, 3.0))

    # Write CSV back
    fieldnames = list(rows[0].keys())
    with open(JOBS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nDone. Patched: {patched} | Failed/expired: {failed}")
    print("Restart the web app to pick up the updated descriptions.")


if __name__ == "__main__":
    main()
