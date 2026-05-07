#!/usr/bin/env python3
"""
Job Search Pipeline — Review Generator
=======================================
Reads jobs_db.csv and score_rationales.json, generates a self-contained
review.html with all job data embedded. Run this after score.py.

Usage:
    python3 generate_review.py

Output:
    review.html  — open directly in any browser
"""

import csv, json, html, subprocess, sys
from pathlib import Path
from datetime import datetime

BASE_DIR       = Path(__file__).parent
JOBS_DB        = BASE_DIR / "jobs_db.csv"
RATIONALES     = BASE_DIR / "score_rationales.json"
OUTPUT         = BASE_DIR / "review.html"

def load_data():
    if not JOBS_DB.exists():
        return []
    rows = list(csv.DictReader(open(JOBS_DB, encoding="utf-8")))
    try:
        rats = json.load(open(RATIONALES, encoding="utf-8"))
    except Exception:
        rats = {}
    for row in rows:
        row["rationale"] = rats.get(row["job_id"], {})
    return rows

def generate(jobs):
    scored  = [j for j in jobs if j["status"] == "scored"]
    scored.sort(key=lambda j: float(j.get("score_overall") or 0), reverse=True)
    reviewed = [j for j in jobs if j["status"] in ("approved", "maybe", "rejected")]
    reviewed.sort(key=lambda j: float(j.get("score_overall") or 0), reverse=True)

    data_js = json.dumps(jobs, ensure_ascii=False)
    generated_at = datetime.now().strftime("%d %b %Y %H:%M")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Job Review — {generated_at}</title>
<style>
:root {{ color-scheme: light; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: #f0f2f5; color: #1e293b; min-height: 100vh;
}}
#app {{ max-width: 820px; margin: 0 auto; padding: 20px; }}

.header {{
  display: flex; align-items: center; gap: 12px;
  background: white; border: 1px solid #e2e8f0;
  border-radius: 12px; padding: 16px 20px; margin-bottom: 6px;
}}
.header h1 {{ font-size: 17px; font-weight: 700; flex: 1; }}
.gen-time {{ font-size: 11px; color: #94a3b8; }}

.pills {{ display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 16px; padding: 0 2px; }}
.pill {{ padding: 3px 9px; border-radius: 20px; font-size: 11px; font-weight: 600; }}
.pill-todo  {{ background: #dbeafe; color: #1d4ed8; }}
.pill-app   {{ background: #dcfce7; color: #15803d; }}
.pill-maybe {{ background: #fef3c7; color: #b45309; }}
.pill-rej   {{ background: #fee2e2; color: #b91c1c; }}

.copy-bar {{
  background: #1e293b; color: #f8fafc; border-radius: 12px;
  padding: 14px 18px; margin-bottom: 16px; display: none;
  align-items: center; gap: 12px;
}}
.copy-bar.visible {{ display: flex; }}
.copy-bar p {{ flex: 1; font-size: 13px; }}
.copy-bar p span {{ color: #94a3b8; font-size: 11px; display: block; margin-top: 2px; }}
.copy-btn {{
  padding: 8px 16px; background: #3b82f6; color: white; border: none;
  border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; white-space: nowrap;
}}
.copy-btn:hover {{ background: #2563eb; }}
.copy-btn.copied {{ background: #16a34a; }}

.section-label {{
  font-size: 11px; font-weight: 700; text-transform: uppercase;
  letter-spacing: .06em; color: #94a3b8; margin: 20px 0 8px 2px;
}}
.empty {{
  text-align: center; padding: 28px; color: #94a3b8; font-size: 13px;
  background: white; border: 1px dashed #e2e8f0; border-radius: 12px;
}}

.card {{
  background: white; border: 1px solid #e2e8f0; border-radius: 12px;
  padding: 18px 20px; margin-bottom: 10px; transition: box-shadow .15s;
}}
.card:hover {{ box-shadow: 0 3px 12px rgba(0,0,0,.07); }}
.card.is-reviewed {{ opacity: .75; }}

.card-top {{ display: flex; gap: 14px; align-items: flex-start; margin-bottom: 14px; }}
.job-info {{ flex: 1; min-width: 0; }}
.job-title {{ font-size: 15px; font-weight: 700; margin-bottom: 3px; }}
.job-co    {{ font-size: 13px; font-weight: 500; color: #3b82f6; margin-bottom: 3px; }}
.job-meta  {{ font-size: 12px; color: #64748b; }}

.score-ring {{
  width: 68px; height: 68px; border-radius: 50%; border: 3px solid;
  display: flex; flex-direction: column; align-items: center;
  justify-content: center; flex-shrink: 0;
}}
.score-ring .num   {{ font-size: 19px; font-weight: 800; line-height: 1; }}
.score-ring .denom {{ font-size: 9px; opacity: .65; font-weight: 500; }}

.bars {{ display: grid; grid-template-columns: 1fr 1fr; gap: 7px 18px; margin-bottom: 12px; }}
.bar-hd {{ display: flex; justify-content: space-between; font-size: 11px; color: #64748b; margin-bottom: 3px; }}
.bar-track {{ height: 5px; background: #f1f5f9; border-radius: 3px; overflow: hidden; }}
.bar-fill  {{ height: 100%; border-radius: 3px; }}

details {{ margin-bottom: 8px; }}
details summary {{
  font-size: 12px; color: #64748b; cursor: pointer;
  user-select: none; list-style: none; padding: 3px 0;
}}
details summary::-webkit-details-marker {{ display: none; }}
details summary::before {{ content: '▶ '; font-size: 9px; }}
details[open] summary::before {{ content: '▼ '; }}
details summary:hover {{ color: #3b82f6; }}
.rat-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 7px; margin-top: 8px; }}
.rat-item {{ background: #f8fafc; border-radius: 8px; padding: 8px 10px; }}
.rat-dim  {{ font-size: 11px; font-weight: 700; color: #1e293b; margin-bottom: 3px; }}
.rat-text {{ font-size: 11.5px; color: #475569; line-height: 1.5; }}
.desc-text {{
  font-size: 12px; color: #475569; line-height: 1.6; margin-top: 8px;
  max-height: 200px; overflow-y: auto;
}}

.card-footer {{
  display: flex; align-items: flex-start; gap: 10px; flex-wrap: wrap;
  margin-top: 12px; padding-top: 12px; border-top: 1px solid #f1f5f9;
}}
.li-btn {{
  padding: 6px 13px; background: #0a66c2; color: white; text-decoration: none;
  border-radius: 8px; font-size: 12px; font-weight: 500; white-space: nowrap; align-self: center;
}}
.li-btn:hover {{ background: #085fa8; }}
.action-area {{ flex: 1; min-width: 200px; display: flex; flex-direction: column; gap: 7px; }}
.notes-ta {{
  width: 100%; padding: 6px 9px; border: 1px solid #e2e8f0; border-radius: 8px;
  font-size: 12px; font-family: inherit; resize: none; height: 34px; color: #1e293b;
}}
.notes-ta:focus {{ outline: none; border-color: #3b82f6; }}
.btns {{ display: flex; gap: 6px; }}
.btn {{
  padding: 6px 13px; border: none; border-radius: 8px;
  font-size: 12px; font-weight: 600; cursor: pointer; transition: all .12s;
}}
.btn:hover {{ opacity: .82; }}
.btn-app  {{ background: #dcfce7; color: #15803d; }}
.btn-may  {{ background: #fef3c7; color: #b45309; }}
.btn-rej  {{ background: #fee2e2; color: #b91c1c; }}
.btn-undo {{ background: #f1f5f9; color: #475569; font-size: 11px; padding: 4px 10px; }}

.status-badge {{ padding: 4px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; }}
.sb-approved {{ background: #dcfce7; color: #15803d; }}
.sb-maybe    {{ background: #fef3c7; color: #b45309; }}
.sb-rejected {{ background: #fee2e2; color: #b91c1c; }}
.rev-notes   {{ font-size: 12px; color: #64748b; font-style: italic; margin-top: 5px; }}
</style>
</head>
<body>
<div id="app">
  <div class="header">
    <h1>Job Review</h1>
    <span class="gen-time">Generated {generated_at}</span>
  </div>

  <div class="pills" id="pills"></div>

  <div class="copy-bar" id="copy-bar">
    <p>
      Decisions ready to paste into Claude
      <span>Click copy, then paste into the chat to save your decisions</span>
    </p>
    <button class="copy-btn" id="copy-btn" onclick="copyDecisions()">Copy decisions</button>
  </div>

  <div class="section-label">To Review</div>
  <div id="to-review"></div>
  <div class="section-label" id="rev-label" style="display:none">Reviewed this session</div>
  <div id="reviewed"></div>
</div>

<script>
const ALL_JOBS = {data_js};
// decisions: {{job_id: {{status, notes}}}}
const decisions = {{}};

function esc(s) {{
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}}

function render() {{
  const todo = ALL_JOBS.filter(j => j.status === 'scored' && !decisions[j.job_id])
                       .sort((a,b) => parseFloat(b.score_overall) - parseFloat(a.score_overall));
  const done = [
    ...ALL_JOBS.filter(j => j.status in {{approved:1,maybe:1,rejected:1}} && !decisions[j.job_id]),
    ...ALL_JOBS.filter(j => decisions[j.job_id])
  ].sort((a,b) => parseFloat(b.score_overall) - parseFloat(a.score_overall));

  document.getElementById('to-review').innerHTML =
    todo.length ? todo.map(j => card(j, false)).join('') : '<div class="empty">No jobs left to review.</div>';
  document.getElementById('reviewed').innerHTML = done.map(j => card(j, true)).join('');
  document.getElementById('rev-label').style.display = done.length ? '' : 'none';

  const nDec = Object.keys(decisions).length;
  const copyBar = document.getElementById('copy-bar');
  if (nDec > 0) copyBar.classList.add('visible'); else copyBar.classList.remove('visible');
  document.getElementById('copy-btn').textContent = 'Copy ' + nDec + ' decision' + (nDec!==1?'s':'');
  document.getElementById('copy-btn').className = 'copy-btn';

  const app = done.filter(j => (decisions[j.job_id]||j).status === 'approved').length;
  const may = done.filter(j => (decisions[j.job_id]||j).status === 'maybe').length;
  const rej = done.filter(j => (decisions[j.job_id]||j).status === 'rejected').length;
  document.getElementById('pills').innerHTML = [
    todo.length ? `<span class="pill pill-todo">${{todo.length}} to review</span>` : '',
    app         ? `<span class="pill pill-app">${{app}} approved</span>` : '',
    may         ? `<span class="pill pill-maybe">${{may}} maybe</span>` : '',
    rej         ? `<span class="pill pill-rej">${{rej}} rejected</span>` : '',
  ].join('');
}}

function card(job, isReviewed) {{
  const dec   = decisions[job.job_id];
  const status = dec ? dec.status : job.status;
  const notes  = dec ? dec.notes  : (job.review_notes || '');
  const score  = parseFloat(job.score_overall) || 0;
  const col    = score >= 80 ? '#16a34a' : score >= 65 ? '#d97706' : '#dc2626';
  const bg     = score >= 80 ? '#dcfce7' : score >= 65 ? '#fef3c7' : '#fee2e2';
  const sal    = (job.salary_raw && job.salary_raw !== 'None') ? ` · ${{esc(job.salary_raw)}}` : '';
  const id     = job.job_id;

  return `
<div class="card${{isReviewed ? ' is-reviewed' : ''}}" id="c-${{esc(id)}}">
  <div class="card-top">
    <div class="job-info">
      <div class="job-title">${{esc(job.title)}}</div>
      <div class="job-co">${{esc(job.company)}}</div>
      <div class="job-meta">${{esc(job.location)}}${{sal}} · Posted ${{esc(job.posted_at)}}</div>
    </div>
    <div class="score-ring" style="background:${{bg}};color:${{col}};border-color:${{col}}">
      <span class="num">${{score}}</span>
      <span class="denom">/ 100</span>
    </div>
  </div>
  <div class="bars">
    ${{bar('Skills',job.score_skills)}}${{bar('Seniority',job.score_seniority)}}
    ${{bar('Industry',job.score_industry)}}${{bar('Salary',job.score_salary)}}
  </div>
  ${{rationale(job)}}
  <details>
    <summary>Job description</summary>
    <p class="desc-text">${{esc(job.description || 'No description.')}}</p>
  </details>
  <div class="card-footer">
    <a class="li-btn" href="${{esc(job.url)}}" target="_blank">LinkedIn →</a>
    ${{isReviewed ? reviewedFooter(id, status, notes) : actionFooter(id)}}
  </div>
</div>`;
}}

function bar(label, raw) {{
  const v = Math.min(10, Math.max(0, parseFloat(raw)||0));
  const col = v>=8?'#16a34a':v>=6?'#3b82f6':v>=4?'#f59e0b':'#ef4444';
  return `<div class="bar-row">
    <div class="bar-hd"><span>${{label}}</span><span>${{v}}/10</span></div>
    <div class="bar-track"><div class="bar-fill" style="width:${{v*10}}%;background:${{col}}"></div></div>
  </div>`;
}}

function rationale(job) {{
  const r = job.rationale || {{}};
  const dims = [['Skills',r.skills],['Seniority',r.seniority],['Industry',r.industry],['Salary',r.salary]].filter(([,v])=>v);
  if (!dims.length) return '';
  return `<details><summary>Why this score?</summary><div class="rat-grid">
    ${{dims.map(([d,v])=>`<div class="rat-item"><div class="rat-dim">${{d}}</div><div class="rat-text">${{esc(v)}}</div></div>`).join('')}}
  </div></details>`;
}}

function actionFooter(id) {{
  return `<div class="action-area">
    <textarea class="notes-ta" id="n-${{esc(id)}}" placeholder="Notes (optional)…"></textarea>
    <div class="btns">
      <button class="btn btn-app" onclick="decide('${{id}}','approved')">✓ Approve</button>
      <button class="btn btn-may" onclick="decide('${{id}}','maybe')">? Maybe</button>
      <button class="btn btn-rej" onclick="decide('${{id}}','rejected')">✗ Reject</button>
    </div>
  </div>`;
}}

function reviewedFooter(id, status, notes) {{
  const labels = {{approved:'✓ Approved', maybe:'? Maybe', rejected:'✗ Rejected'}};
  const cls    = {{approved:'sb-approved', maybe:'sb-maybe', rejected:'sb-rejected'}};
  const isNew  = !!decisions[id];
  return `<div style="flex:1">
    <span class="status-badge ${{cls[status]||''}}">${{labels[status]||status}}</span>
    ${{notes ? `<div class="rev-notes">"${{esc(notes)}}"</div>` : ''}}
    ${{isNew ? `<br><button class="btn btn-undo" onclick="undo('${{id}}')">↩ Undo</button>` : ''}}
  </div>`;
}}

function decide(jobId, action) {{
  const ta = document.getElementById('n-' + jobId);
  decisions[jobId] = {{ status: action, notes: ta ? ta.value.trim() : '' }};
  render();
}}

function undo(jobId) {{
  delete decisions[jobId];
  render();
}}

function copyDecisions() {{
  const payload = JSON.stringify(decisions, null, 2);
  navigator.clipboard.writeText(payload).then(() => {{
    const btn = document.getElementById('copy-btn');
    btn.textContent = '✓ Copied!';
    btn.className = 'copy-btn copied';
  }});
}}

render();
</script>
</body>
</html>"""

def main():
    jobs = load_data()
    scored_count = sum(1 for j in jobs if j["status"] == "scored")

    if not jobs:
        print("No jobs found in jobs_db.csv")
        return

    html_content = generate(jobs)
    OUTPUT.write_text(html_content, encoding="utf-8")
    print(f"Generated {OUTPUT}")
    print(f"  {scored_count} job(s) ready to review, {len(jobs) - scored_count} already reviewed")

    # Try to open in browser (macOS)
    try:
        subprocess.run(["open", str(OUTPUT)], check=True)
        print("  Opened in browser")
    except Exception:
        print(f"  Open manually: {OUTPUT}")

if __name__ == "__main__":
    main()
