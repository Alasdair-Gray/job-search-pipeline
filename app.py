"""
Job Search Pipeline — Flask web application.

Routes:
    GET  /                          Dashboard (job list)
    GET  /job/<job_id>              Job detail view
    POST /api/scrape                Trigger scrape.py in background
    POST /api/score                 Trigger score.py in background
    GET  /api/status                Poll running task state
    GET  /api/stats                 Summary stats (JSON)
    POST /api/launch-cv-builder/<id> Hand job to CV builder

Run locally:
    python app.py

On Render:
    gunicorn app:app
"""

import os
import sys
import threading
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, url_for

import db

BASE_DIR = Path(__file__).parent
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")


# ---------------------------------------------------------------------------
# Background task state
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_task: dict = {
    "running":      False,
    "type":         None,   # "scrape" | "score"
    "log":          [],
    "started_at":   None,
    "completed_at": None,
    "error":        None,
}


def _append_log(line: str):
    with _lock:
        _task["log"].append(line)


def _run_script(script_name: str, task_type: str):
    """
    Run a pipeline script as a subprocess, streaming its stdout to _task['log'].
    Syncs the CSV output into SQLite when done.
    Called in a daemon thread — never call directly.
    """
    import subprocess

    with _lock:
        _task.update({
            "running":      True,
            "type":         task_type,
            "log":          [f"▶ Starting {task_type}…"],
            "started_at":   datetime.utcnow().isoformat(),
            "completed_at": None,
            "error":        None,
        })

    env = {**os.environ, "DATA_DIR": str(db.DATA_DIR)}

    try:
        proc = subprocess.Popen(
            [sys.executable, str(BASE_DIR / script_name)],
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
        for line in proc.stdout:
            _append_log(line.rstrip())
        proc.wait()

        # Sync CSV → SQLite regardless of exit code
        _append_log("Syncing database…")
        synced = db.sync_from_csv()
        _append_log(f"✓ Synced {synced} rows into database.")

        status = "completed" if proc.returncode == 0 else "failed"
        if proc.returncode != 0:
            msg = f"Script exited with code {proc.returncode}"
            _append_log(f"✗ {msg}")
            with _lock:
                _task["error"] = msg

        db.save_run(task_type, status, "\n".join(_task["log"]))

    except Exception as exc:
        _append_log(f"✗ Unexpected error: {exc}")
        with _lock:
            _task["error"] = str(exc)
        db.save_run(task_type, "failed", "\n".join(_task["log"]))

    with _lock:
        _task["running"]      = False
        _task["completed_at"] = datetime.utcnow().isoformat()


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

@app.before_request
def ensure_db():
    """Make sure the schema exists on every cold start."""
    db.init_db()


@app.route("/")
def dashboard():
    status_filter = request.args.get("status", "all")
    jobs  = db.get_jobs(status_filter)
    stats = db.get_stats()
    return render_template("dashboard.html", jobs=jobs, stats=stats,
                           status_filter=status_filter)


@app.route("/job/<job_id>")
def job_detail(job_id):
    job, rationale = db.get_job(job_id)
    if not job:
        return redirect(url_for("dashboard"))
    return render_template("job_detail.html", job=job, rationale=rationale)


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    with _lock:
        if _task["running"]:
            return jsonify({"error": "A task is already running."}), 409
    t = threading.Thread(
        target=_run_script, args=("scrape.py", "scrape"), daemon=True
    )
    t.start()
    return jsonify({"status": "started"})


@app.route("/api/score", methods=["POST"])
def api_score():
    with _lock:
        if _task["running"]:
            return jsonify({"error": "A task is already running."}), 409
    t = threading.Thread(
        target=_run_script, args=("score.py", "score"), daemon=True
    )
    t.start()
    return jsonify({"status": "started"})


@app.route("/api/status")
def api_status():
    with _lock:
        return jsonify(dict(_task))


@app.route("/api/stats")
def api_stats():
    return jsonify(db.get_stats())


@app.route("/api/launch-cv-builder/<job_id>", methods=["POST"])
def api_launch_cv_builder(job_id):
    job, _ = db.get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    # TODO: wire up to CV builder scripts once we have the interface.
    # For now we return the job payload — the frontend can display it
    # and we'll hook it into the builder in the next sprint.
    return jsonify({
        "status":  "ready",
        "message": "CV builder integration coming in next sprint.",
        "job": {
            "title":       job["title"],
            "company":     job["company"],
            "location":    job["location"],
            "salary":      job["salary_raw"],
            "description": job["description"],
            "url":         job["url"],
        },
    })


# ---------------------------------------------------------------------------
# Entry point (local dev)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    db.init_db()
    synced = db.sync_from_csv()
    if synced:
        print(f"Synced {synced} jobs from CSV into SQLite.")
    app.run(debug=True, host="0.0.0.0", port=5000)
