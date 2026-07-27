"""AI CEO Agent — the manager of the whole company.

Responsibilities implemented here:
- `plan_day()`   : choose the next category + format to keep the strategic mix
                   (default 50/50 psychology/history) balanced across the calendar.
- `approve()`    : the go/no-go decision on a produced video (quality gate).
- `weekly_report`: analyze performance by category and author a strategy report,
                   persisted to `ceo_reports`.

The CEO reads the databases (content, analytics, topics, ai_memory) but delegates
execution to the specialist agents via the orchestrator — exactly like a manager.
`run()` defaults to producing the weekly report.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from core.agents.base import BaseAgent
from core.database.models import Analytics, CEOReport, Content
from core.database.session import session_scope
from core.llm.base import LLMMessage
from core.registry import register_agent
from core.schemas import QualityReport


@register_agent
class AICEOAgent(BaseAgent):
    name = "ceo"
    folder = "ai_ceo"

    # ── strategic planning ─────────────────────────────────────────────────
    def plan_day(self, video_format: str = "short") -> dict:
        """Pick the category that is furthest below its target share."""
        mix = self.settings.strategy.category_mix
        window = self.settings.strategy.avoid_repeat_window
        with session_scope() as s:
            recent = [c.category for c in s.query(Content)
                      .order_by(Content.created_at.desc()).limit(window).all()]
        counts = defaultdict(int)
        for c in recent:
            counts[c] += 1
        total = max(1, len(recent))

        # Deficit = target share - actual share; pick the largest deficit.
        deficits = {cat: target - counts.get(cat, 0) / total for cat, target in mix.items()}
        category = max(deficits, key=deficits.get) if deficits else "psychology"
        plan = {"category": category, "video_format": video_format,
                "reason": f"category '{category}' is most under-served vs target mix"}
        self.log.info("CEO plan: %s", plan)
        return plan

    # ── approval gate ──────────────────────────────────────────────────────
    def approve(self, quality: QualityReport) -> bool:
        if self.config.get("approve_requires_quality_pass", True):
            decision = quality.passed
        else:
            decision = quality.overall_score >= self.settings.quality.originality_score_min
        self.log.info("CEO approval: %s (overall %.1f)", decision, quality.overall_score)
        return decision

    # ── weekly review ──────────────────────────────────────────────────────
    def run(self, payload: dict | None = None) -> CEOReport:
        return self.weekly_report()

    def weekly_report(self) -> CEOReport:
        period = datetime.now(timezone.utc).strftime(self.config.get("report_period_format", "%Y-W%W"))
        by_cat: dict[str, list[float]] = defaultdict(list)
        totals = {"videos": 0, "views": 0}

        with session_scope() as s:
            published = s.query(Content).filter(Content.status == "published").all()
            totals["videos"] = len(published)
            for c in published:
                rows = s.query(Analytics).filter(Analytics.video_id == c.id).all()
                for a in rows:
                    by_cat[c.category].append(a.retention)
                    totals["views"] += a.views

        cat_perf = {cat: round(sum(v) / len(v), 1) for cat, v in by_cat.items() if v}
        findings = {
            "period": period,
            "videos_published": totals["videos"],
            "total_views": totals["views"],
            "avg_retention_by_category": cat_perf,
            "leader": max(cat_perf, key=cat_perf.get) if cat_perf else None,
        }

        # Narrative summary (LLM if configured; deterministic otherwise).
        try:
            summary = self.llm.generate([LLMMessage("user", f"TASK: ceo_report\nTOPIC: weekly performance")])
        except Exception:
            summary = self._fallback_summary(findings)

        actions = self._recommend_actions(cat_perf)
        report = None
        with session_scope() as s:
            report = CEOReport(period=period, summary=summary.strip(), findings=findings, actions=actions)
            s.add(report)
            s.flush()
            s.expunge(report)
        self.log.info("CEO weekly report %s written (%d videos).", period, totals["videos"])
        return report

    def _fallback_summary(self, findings: dict) -> str:
        leader = findings.get("leader")
        if not leader:
            return "No published videos yet this period. Once content ships, this report will compare category retention, hook styles, and publishing times."
        return (f"This period, {leader} content led on average retention "
                f"({findings['avg_retention_by_category'].get(leader)}%). "
                f"{findings['videos_published']} videos published, {findings['total_views']} total views.")

    def _recommend_actions(self, cat_perf: dict[str, float]) -> list[str]:
        if not cat_perf:
            return ["Ship the first batch of videos to start collecting performance data."]
        leader = max(cat_perf, key=cat_perf.get)
        laggard = min(cat_perf, key=cat_perf.get)
        return [
            f"Increase share of '{leader}' topics slightly next cycle.",
            f"Tighten intros on '{laggard}' content to lift early retention.",
            "Keep shorts under 70s; front-load the hook in the first 3 seconds.",
        ]
