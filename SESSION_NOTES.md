# Job Search Pipeline — Session Notes
_Last updated: 2026-05-01_

> This file is read at the start of each session to restore full context.

---

## Pipeline status

| Stage | Script | Status |
|-------|--------|--------|
| 1 — Scrape | `scrape.py` | ✅ Live-tested 2026-05-01. Working well. |
| 2 — Ingest & filter | `ingest.py` | ✅ Working. Title + location filters added 2026-05-01. |
| 3 — LLM score | `score.py` | Written but NOT yet run. Needs ANTHROPIC_API_KEY in .env first. |
| 4a — Review HTML | `generate_review.py` | Complete and working |
| 4b — Apply decisions | `apply_decisions.py` | Complete and working |
| 4c — Control panel | Cowork artifact `job-review-dashboard` | Needs upgrade — currently sendPrompt launcher only; to be rebuilt as full interactive dashboard with job editing capability |

---

## Scraping approach: JobSpy (switched from Apify 2026-05-01)

**Why switched:** Apify UI changed to a marketplace model; JobSpy is free, open-source, and covers LinkedIn + Indeed + Glassdoor in one call.

**How it works:**
- Loops over each `job_titles` × `locations` combo from `pipeline_config.json`
- Scrapes LinkedIn (primary), Indeed, Glassdoor via `python-jobspy`
- Deduplicates cross-platform results using `rapidfuzz` fuzzy matching (title + company, 88% threshold)
- LinkedIn record preferred when a cross-platform duplicate is found
- Outputs JSON with field names matching `pipeline_config.json` field_mapping — ingest.py unchanged

**LinkedIn rate limit:** ~250 results per search before rate limiting. Fine for daily personal use.

**Seniority field:** LinkedIn only (`job_level`). Will be empty for Indeed/Glassdoor results — expected and acceptable.

---

## Ingest filters (as of 2026-05-01)

Filters run in this order. Each returns True = exclude.

1. **Duplicate** — job_id already in jobs_db.csv
2. **Title** — title contains no PM keyword (PM_TITLE_KEYWORDS list in ingest.py)
3. **Location** — location is explicitly non-UK (NON_UK_LOCATIONS list in ingest.py)
4. **Recency** — posted more than 24 hours ago
5. **Salary** — salary provided AND max is below £120k
6. **Industry** — fintech/financial services keywords in industry field or description
7. **Seniority** — description explicitly requires fewer than 5 years PM experience

**Last live run stats (2026-05-01):** 382 scraped → 97 passed (201 title, 82 location, 2 recency, 0 salary, 0 industry, 0 seniority filtered)

---

## What's needed next session

### Priority 1: Set up Anthropic API key
Alasdair needs to add their Anthropic API key to `.env`:
1. Go to console.anthropic.com → API Keys → Create key
2. Open `.env` in the project folder
3. Add a line: `ANTHROPIC_API_KEY=sk-ant-XXXXXXXX`

### Priority 2: Run the scorer
```bash
cd "/Users/alasdairgray/Documents/CodingProjects/Job app workflow/Job search pipeline"
source venv/bin/activate
python3 score.py
```
This will score the 97 jobs currently in jobs_db.csv using Claude Haiku.

### Priority 3: Review results and check score quality
```bash
python3 generate_review.py
```
Open the generated `review.html` in a browser. Check whether top-scored jobs look right. If scoring seems off, revisit scoring weights in `pipeline_config.json`.

### Priority 4: Upgrade the Cowork artifact (job review dashboard)
Rebuild `job-review-dashboard` artifact as a full interactive dashboard where Alasdair can:
- See today's top-scored jobs
- Edit job details inline
- Mark jobs to send to the CV Builder skill
- Apply decisions (apply / skip / save for later)

### Priority 5: Daily scheduling
Use the `schedule` skill to automate the full pipeline daily.

---

## Key technical facts

- **All scripts run from Mac terminal** — not from Cowork's shell sandbox (network-blocked for job sites).
- **Virtual environment:** must activate before running scripts:
  `source "/Users/alasdairgray/Documents/CodingProjects/Job app workflow/Job search pipeline/venv/bin/activate"`
- **python3** not `python` on macOS.
- **Scoring model**: claude-haiku-4-5-20251001, weights in pipeline_config.json (skills 40%, seniority 25%, industry 20%, salary 15%).
- **CV profile source**: `../Job app CV builder/Job app CV builder tech files/cv_master_database.json`
- **Current DB**: 97 jobs, all status=new, none yet scored.

---

## How to run the full pipeline (terminal commands)

```bash
BASE="/Users/alasdairgray/Documents/CodingProjects/Job app workflow/Job search pipeline"

# Stage 1+2: Scrape and ingest
python3 "$BASE/scrape.py"

# Stage 3: Score new jobs
python3 "$BASE/score.py"

# Stage 4a: Generate review page (opens in browser)
python3 "$BASE/generate_review.py"

# Stage 4b: After reviewing in browser, copy the decisions JSON and run:
python3 "$BASE/apply_decisions.py" '<paste_json_here>'
```
