"""
Job Search Pipeline — SQLite database layer for the web app.

Reads from jobs_db.csv and score_rationales.json (written by the existing
pipeline scripts) and stores them in a SQLite database for the web UI.

Set DATA_DIR env var to control where the SQLite file lives.
Defaults to the same directory as this file (good for local dev).
On Render, set DATA_DIR=/data (persistent disk mount point).
"""

import csv
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE_DIR)))
DB_PATH  = DATA_DIR / "jobs.db"


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def _conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def init_db():
    """Create tables if they don't exist. Safe to call on every startup."""
    with _conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id          TEXT PRIMARY KEY,
                title           TEXT,
                company         TEXT,
                location        TEXT,
                salary_raw      TEXT,
                salary_min_gbp  INTEGER,
                salary_max_gbp  INTEGER,
                description     TEXT,
                url             TEXT,
                posted_at       TEXT,
                scraped_at      TEXT,
                industry        TEXT,
                employment_type TEXT,
                seniority       TEXT,
                status          TEXT DEFAULT 'new',
                score_overall   REAL,
                score_skills    REAL,
                score_seniority REAL,
                score_industry  REAL,
                score_salary    REAL,
                review_notes    TEXT
            );

            CREATE TABLE IF NOT EXISTS score_rationales (
                job_id    TEXT PRIMARY KEY,
                skills    TEXT,
                seniority TEXT,
                industry  TEXT,
                salary    TEXT,
                scored_at TEXT
            );

            CREATE TABLE IF NOT EXISTS pipeline_runs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                run_type     TEXT,
                started_at   TEXT,
                completed_at TEXT,
                status       TEXT,
                log_output   TEXT
            );
        """)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _f(v):
    try:
        return float(v) if v not in (None, "") else None
    except (ValueError, TypeError):
        return None


def _i(v):
    try:
        return int(float(v)) if v not in (None, "") else None
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# CSV → SQLite sync
# ---------------------------------------------------------------------------

def sync_from_csv() -> int:
    """
    Import jobs_db.csv and score_rationales.json into SQLite.
    Uses INSERT OR REPLACE so it's safe to call repeatedly.
    Returns the number of rows synced.
    """
    csv_path = BASE_DIR / "jobs_db.csv"
    rat_path = BASE_DIR / "score_rationales.json"

    if not csv_path.exists():
        return 0

    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    rationales: dict = {}
    if rat_path.exists():
        with open(rat_path, encoding="utf-8") as f:
            rationales = json.load(f)

    with _conn() as conn:
        for r in rows:
            conn.execute(
                """INSERT OR REPLACE INTO jobs
                   (job_id, title, company, location,
                    salary_raw, salary_min_gbp, salary_max_gbp,
                    description, url, posted_at, scraped_at,
                    industry, employment_type, seniority, status,
                    score_overall, score_skills, score_seniority,
                    score_industry, score_salary, review_notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    r.get("job_id"),        r.get("title"),         r.get("company"),
                    r.get("location"),      r.get("salary_raw"),
                    _i(r.get("salary_min_gbp")),  _i(r.get("salary_max_gbp")),
                    r.get("description"),   r.get("url"),
                    r.get("posted_at"),     r.get("scraped_at"),
                    r.get("industry"),      r.get("employment_type"),
                    r.get("seniority"),     r.get("status", "new"),
                    _f(r.get("score_overall")),   _f(r.get("score_skills")),
                    _f(r.get("score_seniority")), _f(r.get("score_industry")),
                    _f(r.get("score_salary")),    r.get("review_notes", ""),
                ),
            )

        for job_id, rat in rationales.items():
            conn.execute(
                """INSERT OR REPLACE INTO score_rationales
                   (job_id, skills, seniority, industry, salary, scored_at)
                   VALUES (?,?,?,?,?,?)""",
                (
                    job_id,
                    rat.get("skills", ""),
                    rat.get("seniority", ""),
                    rat.get("industry", ""),
                    rat.get("salary", ""),
                    rat.get("scored_at", ""),
                ),
            )

    return len(rows)


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def get_jobs(status_filter: str | None = None) -> list[dict]:
    """Return jobs ordered by score (highest first). Unscored jobs last."""
    with _conn() as conn:
        if status_filter and status_filter != "all":
            rows = conn.execute(
                """SELECT * FROM jobs WHERE status = ?
                   ORDER BY score_overall DESC""",
                (status_filter,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM jobs
                   ORDER BY score_overall DESC"""
            ).fetchall()
    return [dict(r) for r in rows]


def get_job(job_id: str) -> tuple[dict | None, dict | None]:
    """Return (job, rationale) for a single job. Either may be None."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        rat = conn.execute(
            "SELECT * FROM score_rationales WHERE job_id = ?", (job_id,)
        ).fetchone()
    return (dict(row) if row else None), (dict(rat) if rat else None)


def get_stats() -> dict:
    """Return summary statistics for the dashboard header."""
    with _conn() as conn:
        total      = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        scored     = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'scored'").fetchone()[0]
        new_count  = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'new'").fetchone()[0]
        last_scrape = conn.execute("SELECT MAX(scraped_at) FROM jobs").fetchone()[0]
        top_score  = conn.execute("SELECT MAX(score_overall) FROM jobs").fetchone()[0]

    last_fmt = "Never"
    if last_scrape:
        try:
            dt = datetime.fromisoformat(last_scrape.replace("Z", "+00:00"))
            last_fmt = dt.strftime("%-d %b %Y, %H:%M")
        except Exception:
            last_fmt = last_scrape[:16]

    return {
        "total":        total,
        "scored":       scored,
        "new":          new_count,
        "last_scraped": last_fmt,
        "top_score":    round(top_score, 1) if top_score is not None else None,
    }


# ---------------------------------------------------------------------------
# Pipeline run log
# ---------------------------------------------------------------------------

def save_run(run_type: str, status: str, log_output: str):
    now = datetime.utcnow().isoformat()
    with _conn() as conn:
        conn.execute(
            """INSERT INTO pipeline_runs
               (run_type, started_at, completed_at, status, log_output)
               VALUES (?, ?, ?, ?, ?)""",
            (run_type, now, now, status, log_output),
        )
