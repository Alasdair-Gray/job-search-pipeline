#!/usr/bin/env python3
"""
Called by the Review UI artifact. Prints all jobs + rationales as JSON to stdout.
"""
import csv, json, glob
from pathlib import Path

ms = glob.glob('/sessions/*/mnt/CodingProjects/Job app workflow/Job search pipeline/jobs_db.csv')
if not ms:
    print('[]')
else:
    base = Path(ms[0]).parent
    rows = list(csv.DictReader(open(base / 'jobs_db.csv', encoding='utf-8')))
    try:
        rats = json.load(open(base / 'score_rationales.json', encoding='utf-8'))
    except Exception:
        rats = {}
    for r in rows:
        r['rationale'] = rats.get(r['job_id'], {})
    print(json.dumps(rows))
