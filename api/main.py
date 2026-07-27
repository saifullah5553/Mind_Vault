"""FastAPI backend + monitoring dashboard.

Exposes read endpoints over the databases and a trigger endpoint to launch a
production run in the background. The dashboard (dashboard/index.html) is a
zero-build static page that reads these endpoints.

Run:
    uvicorn api.main:app --reload
    open http://127.0.0.1:8000/dashboard
"""

from __future__ import annotations

import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import func

from core.config import ROOT_DIR, get_settings
from core.database.models import (AgentRun, Analytics, CEOReport, Content,
                                  ContentStatus, Topic)
from core.database.session import init_db, session_scope
from core.logging_setup import get_logger
from core.registry import list_agents, load_all_agents

log = get_logger("api")
app = FastAPI(title="Mind_Vault", version="0.1.0",
              description="Autonomous educational media engine — psychology & history.")


@app.on_event("startup")
def _startup() -> None:
    init_db()
    load_all_agents()
    log.info("API up. Agents: %s", ", ".join(list_agents()))


# ── health & meta ───────────────────────────────────────────────────────────
@app.get("/health")
def health() -> dict:
    try:
        with session_scope() as s:
            s.query(Content).count()
        db_ok = True
    except Exception as exc:  # pragma: no cover
        db_ok = False
        log.error("DB health failed: %s", exc)
    return {"status": "ok" if db_ok else "degraded", "db": db_ok,
            "provider": get_settings().llm.provider}


@app.get("/api/agents")
def agents() -> dict:
    load_all_agents()
    return {"agents": list_agents()}


# ── content ─────────────────────────────────────────────────────────────────
@app.get("/api/content")
def content(limit: int = 50) -> list[dict]:
    with session_scope() as s:
        rows = s.query(Content).order_by(Content.created_at.desc()).limit(limit).all()
        return [_content_dict(c) for c in rows]


@app.get("/api/calendar")
def calendar(rebuild: bool = False, days: int | None = None) -> list[dict]:
    from core.calendar import build_calendar, load_calendar
    return build_calendar(days=days) if rebuild else load_calendar()


@app.get("/api/topics")
def topics(limit: int = 50) -> list[dict]:
    with session_scope() as s:
        rows = s.query(Topic).order_by(Topic.total_score.desc()).limit(limit).all()
        return [{"id": t.id, "topic": t.topic, "angle": t.angle, "category": t.category,
                 "total_score": t.total_score, "status": t.status} for t in rows]


# ── analytics ───────────────────────────────────────────────────────────────
@app.get("/api/analytics/summary")
def analytics_summary() -> dict:
    with session_scope() as s:
        total_views = s.query(func.coalesce(func.sum(Analytics.views), 0)).scalar()
        avg_ret = s.query(func.coalesce(func.avg(Analytics.retention), 0.0)).scalar()
        published = s.query(Content).filter(Content.status == ContentStatus.PUBLISHED.value).count()
        by_cat = dict(
            s.query(Content.category, func.avg(Analytics.retention))
            .join(Analytics, Analytics.video_id == Content.id)
            .group_by(Content.category).all()
        )
    return {"published": published, "total_views": int(total_views),
            "avg_retention": round(float(avg_ret), 1),
            "avg_retention_by_category": {k: round(float(v), 1) for k, v in by_cat.items()}}


@app.get("/api/ceo/report")
def ceo_report() -> dict:
    with session_scope() as s:
        report = s.query(CEOReport).order_by(CEOReport.created_at.desc()).first()
        if not report:
            return {"summary": "No CEO report yet. Publish content, then run the weekly review.",
                    "findings": {}, "actions": []}
        return {"period": report.period, "summary": report.summary,
                "findings": report.findings, "actions": report.actions}


@app.get("/api/runs")
def runs(limit: int = 40) -> list[dict]:
    with session_scope() as s:
        rows = s.query(AgentRun).order_by(AgentRun.created_at.desc()).limit(limit).all()
        return [{"run_id": r.run_id, "agent": r.agent, "status": r.status,
                 "duration_ms": r.duration_ms, "error": r.error} for r in rows]


# ── trigger a production run ─────────────────────────────────────────────────
class RunRequest(BaseModel):
    category: str | None = None
    video_format: str = "short"


_JOBS: dict[str, str] = {}


def _background_run(job_id: str, category: str | None, video_format: str) -> None:
    from core.orchestrator import Orchestrator
    try:
        ctx = Orchestrator().produce(category=category, video_format=video_format)
        _JOBS[job_id] = f"done: {ctx.run_id} ({'ok' if not ctx.extra.get('failed_stage') else 'failed'})"
    except Exception as exc:  # pragma: no cover
        _JOBS[job_id] = f"error: {exc}"


@app.post("/api/pipeline/run")
def pipeline_run(req: RunRequest) -> dict:
    if req.video_format not in ("short", "long"):
        raise HTTPException(400, "video_format must be short|long")
    job_id = uuid.uuid4().hex[:8]
    _JOBS[job_id] = "running"
    threading.Thread(target=_background_run, args=(job_id, req.category, req.video_format),
                     daemon=True).start()
    return {"job_id": job_id, "status": "started"}


@app.get("/api/pipeline/status/{job_id}")
def pipeline_status(job_id: str) -> dict:
    return {"job_id": job_id, "status": _JOBS.get(job_id, "unknown")}


# ── dashboard ────────────────────────────────────────────────────────────────
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard() -> str:
    path = ROOT_DIR / "dashboard" / "index.html"
    if not path.exists():
        return HTMLResponse("<h1>Dashboard not found</h1>", status_code=404)
    return path.read_text(encoding="utf-8")


@app.get("/")
def root() -> JSONResponse:
    return JSONResponse({"service": "Mind_Vault", "docs": "/docs", "dashboard": "/dashboard"})


def _content_dict(c: Content) -> dict:
    return {"id": c.id, "title": c.title, "topic": c.topic, "category": c.category,
            "status": c.status, "quality_score": c.quality_score,
            "video_path": c.video_path, "format": c.video_format,
            "created_at": c.created_at.isoformat() if c.created_at else None}
