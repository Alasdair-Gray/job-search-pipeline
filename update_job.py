#!/usr/bin/env python3
"""
Called by the Review UI artifact. Reads {job_id, status, notes} JSON from stdin,
updates the matching row in jobs_db.csv, prints 'ok' or an error.
"""
import csv, json, glob, sys
from pathlib import Path

try:
    # Accept either a base64-encoded JSON arg (from artifact) or raw JSON on stdin (CLI)
    import base64
    if len(sys.argv) > 1:
        data = json.loads(base64.b64decode(sys.argv[1]).decode())
    else:
        data = json.loads(sys.stdin.read())
    job_id = data['job_id']
    status = data['status']
    notes  = data.get('notes', '')

    ms = glob.glob('/sessions/*/mnt/CodingProjects/Job app workflow/Job search pipeline/jobs_db.csv')
    if not ms:
        print('error: jobs_db.csv not found')
        sys.exit(1)

    db   = Path(ms[0])
    rows = list(csv.DictReader(open(db, encoding='utf-8')))
    for row in rows:
        if row['job_id'] == job_id:
            row['status']       = status
            row['review_notes'] = notes

    fields = list(rows[0].keys())
    with open(db, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    print('ok')

except Exception as e:
    print(f'error: {e}')
    sys.exit(1)
