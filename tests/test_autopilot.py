"""Local autopilot: calendar, preflight safety gates, locking, and run state."""

import os
import time
from datetime import date, timedelta

import pytest

from core.config import get_settings
from scripts import autopilot


@pytest.fixture(autouse=True)
def _own_state_dir(tmp_path):
    """Fresh lock/state per test; storage/_test persists between runs."""
    get_settings().storage.root = str(tmp_path)  # absolute: ROOT_DIR / abs == abs


def _next(weekday: int) -> date:
    d = date(2026, 1, 5)  # a Monday
    return d + timedelta(days=weekday)


def test_plan_follows_publishing_cadence():
    s = get_settings()  # short mon/wed/fri, long sun, review sun
    assert autopilot.plan_jobs(_next(0), s) == ["research", "short", "backup"]
    assert autopilot.plan_jobs(_next(1), s) == ["research", "backup"]
    assert autopilot.plan_jobs(_next(6), s) == ["research", "long", "review", "backup"]


def test_render_blocked_without_real_llm_or_voice():
    s = get_settings()  # conftest: stub LLM + silent TTS
    problems = autopilot.preflight("short", s)
    assert any("stub" in p for p in problems)
    assert any("silence" in p for p in problems)
    assert autopilot.preflight("research", s) == []


def test_render_blocked_if_publishing_becomes_public_and_unreviewed():
    s = get_settings()
    s.autopilot.require_real_llm = s.autopilot.require_voice = False
    assert autopilot.preflight("long", s) == []
    s.publishing.dry_run = False
    s.publishing.require_manual_approval = False
    assert any("publicly" in p for p in autopilot.preflight("long", s))


def test_lock_prevents_overlap_and_recovers_when_stale():
    s = get_settings()
    with autopilot.RunLock(s) as first:
        assert first.held
        with autopilot.RunLock(s) as second:
            assert not second.held
    assert not first.path.exists()

    first.path.write_text("crashed run")
    old = time.time() - (s.autopilot.stale_lock_hours + 1) * 3600
    os.utime(first.path, (old, old))
    with autopilot.RunLock(s) as recovered:
        assert recovered.held


def test_blocked_job_reports_and_exits_nonzero():
    rc = autopilot.main(["--job", "short", "--date", "2026-01-05"])
    assert rc == 1
    report = autopilot._load_state(get_settings())["last_run"]
    assert report["jobs"]["short"]["status"] == "blocked"


def test_render_job_runs_once_per_day():
    s = get_settings()
    s.autopilot.require_real_llm = s.autopilot.require_voice = False
    assert autopilot.main(["--job", "short", "--date", "2026-01-05"]) == 0
    first = autopilot._load_state(s)["last_run"]["jobs"]["short"]
    assert first["status"] in ("in_review", "rejected_before_render", "quality_failed")
    autopilot.main(["--job", "short", "--date", "2026-01-05"])
    again = autopilot._load_state(s)["last_run"]["jobs"]["short"]
    assert again["status"] == "already_done"


def test_dry_run_publish_is_not_counted_as_published():
    """A dry run must not mark content published (analytics would invent data)."""
    from core.database.models import Content
    from core.database.session import session_scope
    from core.orchestrator import Orchestrator

    s = get_settings()
    s.publishing.require_manual_approval = False   # let it reach the publish stage
    assert s.publishing.dry_run
    ctx = Orchestrator().produce(category="history", video_format="short")
    assert ctx.publish_results and all(r.status == "dry_run" for r in ctx.publish_results)
    with session_scope() as db:
        assert db.get(Content, ctx.content_id).status != "published"
