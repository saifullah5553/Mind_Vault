"""Quality Control Agent.

The gate every video must clear before publishing. Produces a full scorecard:

  - hook           : strength of the opening (from the Hook Engine)
  - storytelling   : narrative structure + emotional pull + sentence variety
  - fact           : confidence x coverage of verified facts
  - originality     : 100 - similarity to already-published scripts
  - retention_pred : a heuristic prediction of viewer retention
  - copyright_risk : risk that any asset is not clearable (0 = none)

Each dimension is compared to configured minimums; failures are returned so the
orchestrator can regenerate or hold the video. The scores are explainable
heuristics (no black box) — documented and free to compute.
"""

from __future__ import annotations

import re
from pathlib import Path

from core.agents.base import BaseAgent
from core.database.models import Content
from core.database.session import session_scope
from core.dedup import is_duplicate
from core.registry import register_agent
from core.schemas import PipelineContext, QualityReport

_EMOTION_WORDS = {
    "fear", "love", "betrayed", "alone", "powerful", "fateful", "lost", "secret",
    "shocking", "tragic", "hope", "danger", "death", "survive", "dream", "hidden",
    "forbidden", "desperate", "triumph", "rise", "fall", "collapse",
}
_BEAT_MARKERS = {
    "setup": ("began", "started", "once", "first", "early"),
    "conflict": ("but", "however", "conflict", "problem", "against", "tension"),
    "turn": ("then", "suddenly", "turning point", "changed", "moment", "discovery"),
    "lesson": ("lesson", "today", "remember", "us", "why it matters", "meaning"),
}


@register_agent
class QualityAgent(BaseAgent):
    name = "quality"
    folder = "quality_agent"

    def run(self, payload: PipelineContext) -> QualityReport:
        q = self.settings.quality
        reasons: list[str] = []
        script_text = payload.script.full_text if payload.script else ""

        # 1) Fact accuracy — confidence x coverage.
        usable = [v for v in payload.fact_verdicts if v.status in ("approved", "needs_verification")]
        if payload.fact_verdicts:
            avg_conf = sum(v.confidence for v in usable) / len(usable) if usable else 0.0
            coverage = len(usable) / len(payload.fact_verdicts) * 100
            fact_score = round(0.5 * avg_conf + 0.5 * coverage, 1)
        else:
            fact_score = 0.0
        if fact_score < q.fact_score_min:
            reasons.append(f"fact_score {fact_score} < {q.fact_score_min}")

        # 2) Originality.
        originality = self._originality(payload)
        if originality < q.originality_score_min:
            reasons.append(f"originality {originality} < {q.originality_score_min}")

        # 3) Hook.
        hook_score = payload.selected_hook.total if payload.selected_hook else 0.0
        if hook_score < q.hook_score_min:
            reasons.append(f"hook_score {hook_score} < {q.hook_score_min}")

        # 4) Storytelling and 5) retention prediction are ADVISORY: they are scored
        #    and surfaced in the review bundle for the human to judge, but they do
        #    NOT hard-fail (which would trigger expensive full re-renders). Only a
        #    very low storytelling score contributes to the hard gate, via `overall`.
        storytelling = self._storytelling(payload, script_text)
        retention = self._retention_prediction(payload, hook_score, storytelling)

        # 6) Media checks.
        audio_ok = bool(payload.voice and Path(payload.voice.audio_path).exists()
                        and payload.voice.duration > 0)
        visual_ok = bool(payload.video and Path(payload.video.video_path).exists())
        if q.audio_check and not audio_ok:
            reasons.append("audio check failed")
        if q.visual_check and not visual_ok:
            reasons.append("visual check failed")

        # 7) Copyright risk — all assets self-generated; only user-supplied music
        #    could add risk (and we require it be royalty-free).
        copyright_risk_score = self._copyright_risk(payload)
        copyright_risk = "low" if copyright_risk_score < 34 else ("medium" if copyright_risk_score < 67 else "high")
        if copyright_risk != "low" and q.copyright_risk_max == "low":
            reasons.append(f"copyright risk {copyright_risk}")

        w = self.config.get("weights", {})
        media_score = 100.0 if (audio_ok and visual_ok) else 50.0
        overall = round(
            w.get("fact", 0.22) * fact_score
            + w.get("originality", 0.20) * originality
            + w.get("hook", 0.18) * hook_score
            + w.get("storytelling", 0.18) * storytelling
            + w.get("retention", 0.12) * retention
            + w.get("media", 0.10) * media_score, 1)

        # Overall floor catches genuinely weak videos without per-dimension churn.
        overall_min = self.config.get("overall_min", 70)
        if overall < overall_min:
            reasons.append(f"overall {overall} < {overall_min}")

        passed = not reasons
        scorecard = {
            "hook": hook_score, "storytelling": storytelling, "fact_confidence": fact_score,
            "originality": originality, "retention_prediction": retention,
            "copyright_risk": copyright_risk_score, "overall": overall,
        }
        self.log.info("QA overall=%.1f passed=%s | hook=%.0f story=%.0f fact=%.0f orig=%.0f ret=%.0f risk=%.0f",
                      overall, passed, hook_score, storytelling, fact_score, originality,
                      retention, copyright_risk_score)
        return QualityReport(
            fact_score=fact_score, originality_score=originality, hook_score=hook_score,
            storytelling_score=storytelling, retention_prediction=retention,
            copyright_risk_score=copyright_risk_score, audio_ok=audio_ok, visual_ok=visual_ok,
            copyright_risk=copyright_risk, overall_score=overall, passed=passed,
            reasons=reasons, scorecard=scorecard,
        )

    # ── scoring helpers ─────────────────────────────────────────────────────
    def _originality(self, ctx: PipelineContext) -> float:
        script_text = ctx.script.full_text if ctx.script else (ctx.topic.angle if ctx.topic else "")
        if not script_text:
            return 0.0
        with session_scope() as s:
            prior = [c.script for c in s.query(Content).filter(
                Content.status == "published", Content.id != (ctx.content_id or -1)).all() if c.script]
        _, sim = is_duplicate(script_text, prior)
        return round((1.0 - sim) * 100, 1)

    def _storytelling(self, ctx: PipelineContext, text: str) -> float:
        if not text:
            return 0.0
        low = text.lower()
        # (a) Narrative beats present (setup/conflict/turn/lesson).
        beats = sum(1 for _, words in _BEAT_MARKERS.items() if any(w in low for w in words))
        beat_score = beats / len(_BEAT_MARKERS) * 100
        # (b) Emotional pull.
        words = re.findall(r"[a-z']+", low)
        emo = sum(1 for w in words if w in _EMOTION_WORDS)
        emo_score = min(100, emo / max(1, len(words)) * 4000)  # ~2.5% emotive words -> 100
        # (c) Sentence-length variety (good pacing isn't monotone).
        sents = [len(s.split()) for s in re.split(r"[.!?]+", text) if s.strip()]
        if len(sents) > 2:
            mean = sum(sents) / len(sents)
            var = sum((n - mean) ** 2 for n in sents) / len(sents)
            variety = min(100, (var ** 0.5) / max(1, mean) * 200)
        else:
            variety = 40
        # (d) Structure present (has distinct sections).
        structure = 100 if (ctx.script and ctx.script.introduction and ctx.script.ending) else 60
        return round(0.4 * beat_score + 0.25 * emo_score + 0.15 * variety + 0.2 * structure, 1)

    def _retention_prediction(self, ctx: PipelineContext, hook_score: float, storytelling: float) -> float:
        # Heuristic: strong hook + a question/curiosity opener + good pacing + on-target
        # duration predict higher retention. Honest proxy until real analytics train it.
        score = 0.45 * hook_score + 0.25 * storytelling
        # Opening question / curiosity in the first line lifts early retention.
        first = (ctx.selected_hook.text if ctx.selected_hook else "").lower()
        if "?" in first or any(w in first for w in ("why", "what if", "secret", "reason", "hidden")):
            score += 8
        # Pacing: average scene duration (shorter cuts hold attention on shorts).
        if ctx.scene_plan and ctx.scene_plan.scenes:
            avg = sum(s.duration for s in ctx.scene_plan.scenes) / len(ctx.scene_plan.scenes)
            if avg <= 5.5:
                score += 6
            elif avg > 8:
                score -= 6
        # Duration on-target for the format.
        fmt = self.settings.formats.short if ctx.video_format == "short" else self.settings.formats.long
        dur = ctx.video.duration if ctx.video else 0
        lo, hi = fmt.duration_seconds
        if dur and lo <= dur <= hi:
            score += 6
        elif dur:
            score -= 6
        return round(max(0.0, min(100.0, score)), 1)

    def _copyright_risk(self, ctx: PipelineContext) -> float:
        # Self-generated script/voice/images/procedural-music -> ~0 risk. Only
        # USER-supplied music raises it (and the operator attests it's royalty-free).
        risk = 5.0
        if self.settings.video.background_music:
            from core.media.music import _user_tracks
            risk += 12 if _user_tracks() else 1  # procedural bed is self-generated => safe
        return round(min(100.0, risk), 1)
