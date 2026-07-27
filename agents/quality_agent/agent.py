"""Quality Control Agent.

The gate every video must clear before publishing. Combines fact accuracy,
originality (from the dedup engine), hook strength, and media checks into an
overall score, and compares each dimension against the configured minimums.
Returns a `QualityReport`; the orchestrator sends failures back for regeneration.
"""

from __future__ import annotations

from pathlib import Path

from core.agents.base import BaseAgent
from core.dedup import is_duplicate
from core.database.models import Content
from core.database.session import session_scope
from core.registry import register_agent
from core.schemas import PipelineContext, QualityReport


@register_agent
class QualityAgent(BaseAgent):
    name = "quality"
    folder = "quality_agent"

    def run(self, payload: PipelineContext) -> QualityReport:
        q = self.settings.quality
        reasons: list[str] = []

        # 1) Fact accuracy — blend of (a) mean confidence of USABLE facts and
        #    (b) coverage (share of claims that survived the checker). A dossier
        #    that is both well-sourced and well-covered clears the bar; a thin or
        #    heavily-rejected one does not.
        usable = [v for v in payload.fact_verdicts if v.status in ("approved", "needs_verification")]
        if payload.fact_verdicts:
            avg_conf = sum(v.confidence for v in usable) / len(usable) if usable else 0.0
            coverage = len(usable) / len(payload.fact_verdicts) * 100
            fact_score = round(0.5 * avg_conf + 0.5 * coverage, 1)
        else:
            fact_score = 0.0
        if fact_score < q.fact_score_min:
            reasons.append(f"fact_score {fact_score} < {q.fact_score_min}")

        # 2) Originality — 100 - max similarity to prior published scripts.
        originality = self._originality(payload)
        if originality < q.originality_score_min:
            reasons.append(f"originality {originality} < {q.originality_score_min}")

        # 3) Hook strength.
        hook_score = payload.selected_hook.total if payload.selected_hook else 0.0
        if hook_score < q.hook_score_min:
            reasons.append(f"hook_score {hook_score} < {q.hook_score_min}")

        # 4) Media checks.
        audio_ok = bool(payload.voice and Path(payload.voice.audio_path).exists()
                        and payload.voice.duration > 0)
        visual_ok = bool(payload.video and Path(payload.video.video_path).exists())
        if q.audio_check and not audio_ok:
            reasons.append("audio check failed")
        if q.visual_check and not visual_ok:
            reasons.append("visual check failed")

        # 5) Copyright risk — all assets are self-generated -> low.
        copyright_risk = "low"

        w = self.config.get("weights", {})
        media_score = 100.0 if (audio_ok and visual_ok) else 50.0
        overall = round(
            w.get("fact", 0.35) * fact_score
            + w.get("originality", 0.30) * originality
            + w.get("hook", 0.20) * hook_score
            + w.get("media", 0.15) * media_score, 1)

        passed = not reasons
        self.log.info("QA overall=%.1f passed=%s (%s)", overall, passed,
                      "; ".join(reasons) or "all gates clear")
        return QualityReport(
            fact_score=fact_score, originality_score=originality, hook_score=hook_score,
            audio_ok=audio_ok, visual_ok=visual_ok, copyright_risk=copyright_risk,
            overall_score=overall, passed=passed, reasons=reasons,
        )

    def _originality(self, ctx: PipelineContext) -> float:
        script_text = ctx.script.full_text if ctx.script else (ctx.topic.angle if ctx.topic else "")
        if not script_text:
            return 0.0
        with session_scope() as s:
            prior = [c.script for c in s.query(Content).filter(
                Content.status == "published", Content.id != (ctx.content_id or -1)).all() if c.script]
        _, sim = is_duplicate(script_text, prior)
        return round((1.0 - sim) * 100, 1)
