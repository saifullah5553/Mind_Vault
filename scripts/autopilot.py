"""Local autopilot: decide today's work and run it on THIS machine.

Real production cannot run on GitHub-hosted runners (no Ollama, no voice model,
no GPU), so this is the scheduled entry point instead. Point Windows Task
Scheduler at `autopilot.cmd` once a day and it will:

    every day      research     refresh trends, topics and competitor intel
    short_days     short        produce one Short (vertical)
    long_days      long         produce one documentary (landscape)
    review_day     review       weekly CEO report (+ learning once analytics is live)
    always         backup       zip the database, config and logs

Each job is checked first (preflight). The autopilot refuses to render when the
result would be junk: Ollama down means placeholder stub scripts, and a missing
Piper voice means silent narration. It also refuses to run if publishing has
been switched to fully automatic public uploads. Finished videos land in the
review folder; nothing is uploaded unless you approve it.

Usage:
    python -m scripts.autopilot                 # run whatever today calls for
    python -m scripts.autopilot --plan          # show today's plan + preflight, run nothing
    python -m scripts.autopilot --job short     # run one job now (repeatable)
    python -m scripts.autopilot --date 2026-11-01 --plan
    python -m scripts.autopilot --force         # re-run jobs already done today
    python -m scripts.autopilot --install-task --time 09:00
    python -m scripts.autopilot --uninstall-task
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from argparse import Namespace
from datetime import date, datetime, timezone
from pathlib import Path

from core.config import ROOT_DIR, Settings, get_settings
from core.logging_setup import get_logger

log = get_logger("scripts.autopilot")

JOBS = ("research", "short", "long", "review", "backup")
RENDER_JOBS = {"short", "long"}
TASK_NAME = "Mind_Vault Autopilot"
_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


# ── calendar ────────────────────────────────────────────────────────────────
def today(s: Settings) -> date:
    """Today's date in the channel's publishing timezone (falls back to local)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(s.publishing.timezone)).date()
    except Exception:
        log.warning("Timezone %r unavailable (pip install tzdata); using local time.",
                    s.publishing.timezone)
        return date.today()


def plan_jobs(day: date, s: Settings) -> list[str]:
    """The jobs the calendar calls for on `day`, in run order."""
    wd = _WEEKDAYS[day.weekday()]
    jobs: list[str] = []
    if s.autopilot.research_daily:
        jobs.append("research")
    # Long-form wins if a day is listed under both (one render per day).
    if wd in s.publishing.long_days:
        jobs.append("long")
    elif wd in s.publishing.short_days:
        jobs.append("short")
    if wd == s.autopilot.review_day:
        jobs.append("review")
    jobs.append("backup")
    return jobs


# ── preflight ───────────────────────────────────────────────────────────────
def _llm_ready(s: Settings) -> str | None:
    if s.llm.provider == "stub":
        return "llm.provider is 'stub' (placeholder scripts); set it to 'ollama'"
    if s.llm.provider != "ollama":
        return None  # another real provider; trust its own error handling
    from core.llm.ollama_provider import OllamaLLM
    o = OllamaLLM(model=s.llm.model, host_env=s.llm.ollama_host_env)
    if not o.is_available():
        return f"Ollama is not responding at {o.host} (start the Ollama app)"
    if not any(s.llm.model in m for m in o.installed_models()):
        return f"Ollama model '{s.llm.model}' is not pulled (ollama pull {s.llm.model})"
    return None


def _voice_ready(s: Settings) -> str | None:
    if s.tts.provider == "silence":
        return "tts.provider is 'silence' (no narration)"
    if s.tts.provider not in ("auto", "piper"):
        return None
    from core.media.tts import _piper_model
    if not _piper_model():
        return "no Piper voice model in storage/voices (python -m scripts.setup_machine)"
    return None


def preflight(job: str, s: Settings) -> list[str]:
    """Reasons `job` must not run right now. Empty list = go."""
    problems: list[str] = []
    if job in RENDER_JOBS:
        pub = s.publishing
        if not pub.dry_run and not pub.require_manual_approval:
            problems.append("publishing would upload publicly with no human approval "
                            "(dry_run and require_manual_approval are both off)")
        if s.autopilot.require_real_llm and (why := _llm_ready(s)):
            problems.append(why)
        if s.autopilot.require_voice and (why := _voice_ready(s)):
            problems.append(why)
        free_gb = shutil.disk_usage(ROOT_DIR).free / 1024 ** 3
        if free_gb < s.autopilot.min_free_gb:
            problems.append(f"only {free_gb:.1f} GB free (< {s.autopilot.min_free_gb} GB)")
    return problems


# ── run state + lock ────────────────────────────────────────────────────────
def _state_dir(s: Settings) -> Path:
    p = ROOT_DIR / s.storage.root
    p.mkdir(parents=True, exist_ok=True)
    return p


def _load_state(s: Settings) -> dict:
    path = _state_dir(s) / "autopilot_state.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(s: Settings, state: dict) -> None:
    (_state_dir(s) / "autopilot_state.json").write_text(
        json.dumps(state, indent=2), encoding="utf-8")


class RunLock:
    """One autopilot at a time: a second launch exits instead of double-rendering."""

    def __init__(self, s: Settings):
        self.path = _state_dir(s) / "autopilot.lock"
        self.stale_after = s.autopilot.stale_lock_hours * 3600
        self.held = False

    def __enter__(self) -> "RunLock":
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                age = time.time() - self.path.stat().st_mtime
                if age < self.stale_after:
                    return self
                log.warning("Removing stale autopilot lock (%.1f h old).", age / 3600)
                self.path.unlink(missing_ok=True)
                continue
            with os.fdopen(fd, "w") as fh:
                fh.write(f"{os.getpid()} {datetime.now(timezone.utc).isoformat()}\n")
            self.held = True
            return self
        return self

    def __exit__(self, *exc) -> None:
        if self.held:
            self.path.unlink(missing_ok=True)


# ── jobs ────────────────────────────────────────────────────────────────────
def _job_research(s: Settings) -> dict:
    from core.registry import get_agent, load_all_agents
    load_all_agents()
    out = {}
    for cat in s.strategy.category_mix:
        trends = get_agent("trend").execute({"category": cat}).output
        topics = get_agent("topic").execute({"category": cat, "trends": trends}).output
        get_agent("competitor").execute({"category": cat})
        out[cat] = len(topics or [])
    return {"status": "ok", "topics": out}


def _job_render(video_format: str) -> dict:
    from core.orchestrator import Orchestrator
    from scripts.run_pipeline import _apply_output_format
    # Default orientation per format (vertical Short, landscape documentary).
    _apply_output_format(Namespace(video_format=video_format, orientation=None,
                                   resolution=None))
    ctx = Orchestrator().produce(category=None, video_format=video_format)
    result = {"run_id": ctx.run_id, "category": ctx.category,
              "topic": ctx.topic.angle if ctx.topic else None,
              "title": ctx.script.title if ctx.script else None}
    if ctx.extra.get("failed_stage"):
        result.update(status="failed", stage=ctx.extra["failed_stage"],
                      error=str(ctx.extra.get("error"))[:300],
                      resume=f"python -m scripts.run_pipeline --resume {ctx.run_id}")
    elif ctx.extra.get("precheck_failed"):
        result.update(status="rejected_before_render",
                      reasons=(ctx.extra.get("precheck") or {}).get("reasons"))
    elif ctx.extra.get("quality_failed"):
        result.update(status="quality_failed",
                      score=ctx.quality.overall_score if ctx.quality else None)
    else:
        result.update(status="in_review", review_dir=ctx.extra.get("review_dir"),
                      video=ctx.video.video_path if ctx.video else None,
                      approve=f"python -m scripts.review approve {ctx.run_id}")
    return result


def _job_review(s: Settings) -> dict:
    from core.registry import get_agent, load_all_agents
    load_all_agents()
    result: dict = {"status": "ok"}
    mode = get_agent("analytics").config.get("mode", "auto")
    if mode == "live":
        result["analytics"] = get_agent("analytics").execute({}).output
        result["learning"] = get_agent("learning").execute({}).output
    else:
        # 'auto'/'simulate' invent figures. Learning from them would steer the
        # channel by fiction, so the loop waits for real platform analytics.
        result["learning"] = f"skipped: analytics mode is '{mode}', not 'live'"
    report = get_agent("ceo").execute({}).output
    result["ceo"] = getattr(report, "summary", None)
    return result


def _job_backup(_s: Settings) -> dict:
    from scripts import backup
    backup.main()
    return {"status": "ok"}


def run_job(job: str, s: Settings) -> dict:
    if job == "research":
        return _job_research(s)
    if job in RENDER_JOBS:
        return _job_render(job)
    if job == "review":
        return _job_review(s)
    if job == "backup":
        return _job_backup(s)
    raise ValueError(f"unknown job {job!r}")


# ── Windows Task Scheduler ──────────────────────────────────────────────────
def _task_ps(at: str) -> str:
    cmd = ROOT_DIR / "autopilot.cmd"
    return (
        f"$a = New-ScheduledTaskAction -Execute '{cmd}' -WorkingDirectory '{ROOT_DIR}'; "
        f"$t = New-ScheduledTaskTrigger -Daily -At '{at}'; "
        # StartWhenAvailable: if the PC was off at that time, run at next boot.
        "$o = New-ScheduledTaskSettingsSet -StartWhenAvailable "
        "-ExecutionTimeLimit (New-TimeSpan -Hours 6) -MultipleInstances IgnoreNew; "
        f"Register-ScheduledTask -TaskName '{TASK_NAME}' -Action $a -Trigger $t "
        "-Settings $o -Description 'Mind_Vault daily research + production (review-gated)' "
        "-Force | Out-Null; 'registered'"
    )


def install_task(at: str) -> int:
    if sys.platform != "win32":
        print("Task Scheduler is Windows-only. On Linux/macOS add a cron entry:\n"
              f"  0 9 * * *  cd {ROOT_DIR} && .venv/bin/python -m scripts.autopilot")
        return 1
    r = subprocess.run(["powershell", "-NoProfile", "-Command", _task_ps(at)],
                       capture_output=True, text=True)
    print((r.stdout or r.stderr).strip())
    return r.returncode


def uninstall_task() -> int:
    r = subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
                       capture_output=True, text=True)
    print((r.stdout or r.stderr).strip())
    return r.returncode


# ── main ────────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run today's Mind_Vault work locally")
    ap.add_argument("--plan", action="store_true", help="show plan + preflight only")
    ap.add_argument("--job", action="append", choices=JOBS,
                    help="run this job instead of the calendar (repeatable)")
    ap.add_argument("--date", help="pretend today is YYYY-MM-DD (for planning)")
    ap.add_argument("--force", action="store_true", help="re-run jobs already done today")
    ap.add_argument("--install-task", action="store_true",
                    help="register a daily Windows scheduled task")
    ap.add_argument("--uninstall-task", action="store_true")
    ap.add_argument("--time", default="09:00", help="daily start time for --install-task")
    args = ap.parse_args(argv)

    if args.install_task:
        return install_task(args.time)
    if args.uninstall_task:
        return uninstall_task()

    s = get_settings()
    day = date.fromisoformat(args.date) if args.date else today(s)
    jobs = args.job or plan_jobs(day, s)
    state = _load_state(s)
    done_today = state.get("done", {})

    print(f"\nMind_Vault autopilot | {day.isoformat()} ({_WEEKDAYS[day.weekday()]})")
    plan = []
    for job in jobs:
        problems = preflight(job, s)
        already = done_today.get(job) == day.isoformat() and not args.force
        plan.append((job, problems, already))
        mark = "done " if already else ("BLOCK" if problems else "ready")
        print(f"  [{mark}] {job}" + (f"  -> {'; '.join(problems)}" if problems else ""))
    if args.plan:
        return 0

    with RunLock(s) as lock:
        if not lock.held:
            print("Another autopilot run is in progress; exiting.")
            return 0
        from core.database.session import init_db
        init_db()

        report = {"date": day.isoformat(),
                  "started": datetime.now(timezone.utc).isoformat(), "jobs": {}}
        ok = True
        for job, problems, already in plan:
            if already:
                report["jobs"][job] = {"status": "already_done"}
                continue
            if problems:
                report["jobs"][job] = {"status": "blocked", "reasons": problems}
                log.warning("Autopilot %s BLOCKED: %s", job, "; ".join(problems))
                ok = False
                continue
            log.info("Autopilot: starting %s", job)
            try:
                res = run_job(job, s)
            except Exception as exc:  # one failed job never stops the others
                log.exception("Autopilot %s crashed", job)
                res = {"status": "crashed", "error": str(exc)[:300]}
            report["jobs"][job] = res
            if res.get("status") in ("ok", "in_review", "rejected_before_render",
                                     "quality_failed"):
                # A rejected script is a finished job: the quality gate did its
                # work. Retrying the same day would just burn hours of CPU.
                done_today[job] = day.isoformat()
            else:
                ok = False
            print(f"  {job}: {res.get('status')}")

        report["finished"] = datetime.now(timezone.utc).isoformat()
        state["done"] = done_today
        state["last_run"] = report
        _save_state(s, state)
        (_state_dir(s) / "autopilot_last_run.json").write_text(
            json.dumps(report, indent=2, default=str), encoding="utf-8")

    for job, res in report["jobs"].items():
        if res.get("approve"):
            print(f"\nReady for review: {res.get('title')}\n  {res['approve']}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
