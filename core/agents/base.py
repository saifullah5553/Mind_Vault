"""BaseAgent — the contract every Mind_Vault agent fulfills.

DESIGN: Agents implement one method: `run(payload) -> result`. Everything else —
timing, structured logging, retry/backoff, error capture, and persisting an
`AgentRun` audit row — is handled here so no agent re-implements ops plumbing.
This directly satisfies the requirement that every agent has clear
responsibility, config, logging, error handling, and is independently testable.

Subclass shape:

    class TrendAgent(BaseAgent):
        name = "trend"
        def run(self, payload):        # pure logic; may raise
            ...
            return TrendItem(...)

Call it via `agent.execute(payload, run_id=...)` to get the full wrapped
lifecycle, or `agent.run(payload)` directly in a unit test.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from core.config import ROOT_DIR, get_settings
from core.database.models import AgentRun
from core.database.session import session_scope
from core.errors import NonRetryableError, with_retry
from core.llm import get_llm
from core.logging_setup import get_logger


@dataclass
class AgentResult:
    agent: str
    status: str                       # success | error
    output: Any = None
    error: str | None = None
    attempts: int = 1
    duration_ms: int = 0
    run_id: str = ""
    meta: dict = field(default_factory=dict)


class BaseAgent:
    """Base class providing logging, config, retry, and run auditing."""

    name: str = "base"                # override in subclass
    folder: str | None = None         # override if folder != f"{name}_agent"

    def __init__(self, config_path: str | Path | None = None):
        self.settings = get_settings()
        self.log = get_logger(f"agent.{self.name}")
        self.llm = get_llm()
        self.config = self._load_agent_config(config_path)

    # ── config ─────────────────────────────────────────────────────────────
    def _default_config_path(self) -> Path:
        folder = self.folder or f"{self.name}_agent"
        return ROOT_DIR / "agents" / folder / "config.yaml"

    def _load_agent_config(self, config_path: str | Path | None) -> dict:
        """Load the agent's own config.yaml if present (optional per-agent tuning)."""
        path = Path(config_path) if config_path else self._default_config_path()
        # Also try folder names that don't follow the `<name>_agent` convention.
        candidates = [path, ROOT_DIR / "agents" / self.name / "config.yaml"]
        for cand in candidates:
            if cand.exists():
                with cand.open("r", encoding="utf-8") as fh:
                    return yaml.safe_load(fh) or {}
        return {}

    # ── the one method subclasses implement ────────────────────────────────
    def run(self, payload: Any) -> Any:  # pragma: no cover - abstract
        raise NotImplementedError(f"Agent {self.name} must implement run().")

    # ── LLM convenience ────────────────────────────────────────────────────
    def llm_text(self, prompt: str, system: str | None = None, **kw: Any) -> str:
        return self.llm.complete(prompt, system=system, **kw)

    # ── the wrapped lifecycle used by the orchestrator ─────────────────────
    def execute(self, payload: Any = None, *, run_id: str | None = None,
                persist: bool = True) -> AgentResult:
        run_id = run_id or uuid.uuid4().hex[:12]
        rel = self.settings.reliability
        started = time.perf_counter()
        attempts_box = {"n": 0}

        def _attempt() -> Any:
            attempts_box["n"] += 1
            self.log.info("start", extra={"agent": self.name, "run_id": run_id,
                                          "event": "start", "stage": self.name})
            return self.run(payload)

        def _on_retry(attempt: int, exc: BaseException) -> None:
            self.log.warning("retry %d after error: %s", attempt, exc,
                             extra={"agent": self.name, "run_id": run_id, "event": "retry"})

        try:
            output = with_retry(
                _attempt,
                retries=rel.max_retries,
                backoff=rel.retry_backoff_seconds,
                on_retry=_on_retry,
            )
            duration_ms = int((time.perf_counter() - started) * 1000)
            result = AgentResult(
                agent=self.name, status="success", output=output,
                attempts=attempts_box["n"], duration_ms=duration_ms, run_id=run_id,
            )
            self.log.info("done in %dms (attempt %d)", duration_ms, attempts_box["n"],
                          extra={"agent": self.name, "run_id": run_id,
                                 "event": "done", "duration_ms": duration_ms})
        except Exception as exc:  # noqa: BLE001 - we record everything
            duration_ms = int((time.perf_counter() - started) * 1000)
            self.log.error("failed after %d attempt(s): %s", attempts_box["n"], exc,
                           extra={"agent": self.name, "run_id": run_id, "event": "error"},
                           exc_info=not isinstance(exc, NonRetryableError))
            result = AgentResult(
                agent=self.name, status="error", error=str(exc),
                attempts=attempts_box["n"], duration_ms=duration_ms, run_id=run_id,
            )

        if persist:
            self._persist_run(result, payload)
        return result

    # ── audit persistence ──────────────────────────────────────────────────
    def _persist_run(self, result: AgentResult, payload: Any) -> None:
        try:
            with session_scope() as s:
                s.add(AgentRun(
                    run_id=result.run_id,
                    agent=self.name,
                    status=result.status,
                    duration_ms=result.duration_ms,
                    attempts=result.attempts,
                    input_summary=_summarize(payload),
                    output_summary=_summarize(result.output),
                    error=result.error,
                ))
        except Exception as exc:  # never let auditing break the pipeline
            self.log.warning("could not persist AgentRun: %s", exc)


def _summarize(obj: Any, limit: int = 500) -> str:
    text = repr(obj)
    return text[:limit] + ("…" if len(text) > limit else "")
