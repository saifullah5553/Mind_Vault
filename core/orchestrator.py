"""The production orchestrator — the automated content pipeline.

Runs the full DAG the brief describes:

    CEO plan → Trend → Topic(+Opportunity) → Research → Fact-check → Hook →
    Script → Visual → Voice → Presenter → Video → Quality → CEO approve →
    SEO → Publish → persist

DESIGN highlights:
- Each specialist runs through `agent.execute()`, so every stage is retried,
  logged, and audited in `agent_runs` automatically.
- A `PipelineContext` threads results between stages and is CHECKPOINTED to disk
  after each stage. If a run dies, `resume()` picks up from the last checkpoint —
  satisfying "never lose generated content / resume from last completed stage".
- Failing the quality gate triggers bounded regeneration (new hook + script)
  before giving up, matching "send back for regeneration".
- The CEO owns category selection and the final approve/reject decision.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from agents.ai_ceo.agent import AICEOAgent
from core.config import ROOT_DIR, get_settings
from core.database.models import Content, ContentMemory, ContentStatus
from core.database.session import session_scope
from core.errors import Mind_VaultError
from core.logging_setup import get_logger
from core.registry import get_agent, load_all_agents
from core.schemas import PipelineContext

log = get_logger("orchestrator")


class Orchestrator:
    def __init__(self) -> None:
        load_all_agents()
        self.settings = get_settings()
        self.ceo = AICEOAgent()
        self._checkpoint_dir = ROOT_DIR / "storage" / "checkpoints"
        self._checkpoint_dir.mkdir(parents=True, exist_ok=True)

    # ── public entry points ────────────────────────────────────────────────
    def produce(self, category: str | None = None, video_format: str = "short",
                run_id: str | None = None) -> PipelineContext:
        """Produce one video end-to-end."""
        run_id = run_id or uuid.uuid4().hex[:12]

        if category is None:
            plan = self.ceo.plan_day(video_format)
            category, video_format = plan["category"], plan["video_format"]

        ctx = PipelineContext(run_id=run_id, category=category, video_format=video_format)
        log.info("=== START run %s | %s | %s ===", run_id, category, video_format)
        return self._run(ctx)

    def resume(self, run_id: str) -> PipelineContext:
        ctx = self._load_checkpoint(run_id)
        if ctx is None:
            raise Mind_VaultError(f"No checkpoint found for run {run_id}")
        log.info("=== RESUME run %s from stages %s ===", run_id, ctx.completed_stages)
        return self._run(ctx)

    # ── the pipeline ───────────────────────────────────────────────────────
    def _run(self, ctx: PipelineContext) -> PipelineContext:
        stages = [
            ("trend", self._stage_trend),
            ("topic", self._stage_topic),
            ("content_record", self._stage_content_record),
            ("research", self._stage_research),
            ("fact", self._stage_fact),
            ("hook", self._stage_hook),
            ("script", self._stage_script),
            ("visual", self._stage_visual),
            ("voice", self._stage_voice),
            ("presenter", self._stage_presenter),
            ("video", self._stage_video),
            ("quality", self._stage_quality),
            ("approve", self._stage_approve),
            ("seo", self._stage_seo),
            ("thumbnail", self._stage_thumbnail),
            ("publish", self._stage_publish),
            ("finalize", self._stage_finalize),
        ]
        for name, fn in stages:
            if name in ctx.completed_stages:
                continue
            try:
                fn(ctx)
            except Mind_VaultError as exc:
                log.error("Stage '%s' failed for run %s: %s", name, ctx.run_id, exc)
                ctx.extra["failed_stage"] = name
                ctx.extra["error"] = str(exc)
                self._checkpoint(ctx)
                return ctx
            ctx.completed_stages.append(name)
            self._checkpoint(ctx)
        log.info("=== DONE run %s ===", ctx.run_id)
        return ctx

    # ── individual stages ──────────────────────────────────────────────────
    def _agent_output(self, name: str, payload, ctx: PipelineContext):
        res = get_agent(name).execute(payload, run_id=ctx.run_id)
        if res.status != "success":
            raise Mind_VaultError(f"{name}: {res.error}")
        return res.output

    def _stage_trend(self, ctx):
        trends = self._agent_output("trend", {"category": ctx.category}, ctx)
        ctx.trend = trends[0] if trends else None
        ctx.extra["trends"] = [t.model_dump() for t in trends]

    def _stage_topic(self, ctx):
        from core.schemas import TrendItem
        trends = [TrendItem(**t) for t in ctx.extra.get("trends", [])]
        ctx.topic = self._agent_output("topic", {"category": ctx.category, "trends": trends}, ctx)

    def _stage_content_record(self, ctx):
        with session_scope() as s:
            content = Content(
                topic=ctx.topic.topic, category=ctx.category,
                subcategory=ctx.topic.subcategory, title=ctx.topic.angle,
                keywords=[], video_format=ctx.video_format, status=ContentStatus.IDEA.value,
            )
            s.add(content)
            s.flush()
            ctx.content_id = content.id

    def _stage_research(self, ctx):
        ctx.dossier = self._agent_output("research", ctx.topic, ctx)
        self._update_content(ctx, status=ContentStatus.RESEARCHED.value)

    def _stage_fact(self, ctx):
        result = self._agent_output("fact", ctx.dossier, ctx)
        ctx.fact_verdicts = result["verdicts"]
        ctx.extra["approved_facts"] = [f.model_dump() for f in result["approved_facts"]]
        if not result["gate_passed"]:
            raise Mind_VaultError("fact gate: not enough verifiable facts")

    def _stage_hook(self, ctx):
        # Hook on the raw subject (e.g. "historical mysteries"), not the already
        # reframed title, so phrasing stays natural.
        result = self._agent_output("hook", {"topic": ctx.topic.topic, "category": ctx.category}, ctx)
        ctx.hooks = result["hooks"]
        ctx.selected_hook = result["selected"]

    def _stage_script(self, ctx):
        from core.schemas import ResearchFact
        facts = [ResearchFact(**f) for f in ctx.extra.get("approved_facts", [])]
        ctx.script = self._agent_output("script", {
            "topic": ctx.topic.topic, "category": ctx.category,
            "hook": ctx.selected_hook.text if ctx.selected_hook else "",
            "facts": facts, "title": ctx.topic.angle, "video_format": ctx.video_format,
        }, ctx)
        self._update_content(ctx, status=ContentStatus.SCRIPTED.value, script=ctx.script.full_text,
                             title=ctx.script.title, keywords=[])

    def _stage_visual(self, ctx):
        ctx.scene_plan = self._agent_output("visual", {"script": ctx.script}, ctx)

    def _stage_voice(self, ctx):
        ctx.voice = self._agent_output("voice", {"script": ctx.script, "run_id": ctx.run_id}, ctx)

    def _stage_presenter(self, ctx):
        result = self._agent_output("presenter", {"voice": ctx.voice, "run_id": ctx.run_id}, ctx)
        # Agent returns a dict; keep the composited overlay + persona metadata.
        ctx.presenter_path = result.get("overlay")
        ctx.extra["presenter"] = {
            "persona": result.get("persona"),
            "disclosure": result.get("disclosure"),
            "clip": result.get("clip"),
            "portrait": result.get("portrait"),
        }

    def _stage_video(self, ctx):
        ctx.video = self._agent_output("video", {
            "scene_plan": ctx.scene_plan, "voice": ctx.voice,
            "run_id": ctx.run_id, "video_format": ctx.video_format,
            "presenter_overlay": ctx.presenter_path,
        }, ctx)
        self._update_content(ctx, status=ContentStatus.PRODUCED.value,
                             video_path=ctx.video.video_path,
                             audio_path=ctx.voice.audio_path if ctx.voice else None)

    def _stage_quality(self, ctx):
        ctx.quality = self._agent_output("quality", ctx, ctx)
        self._update_content(ctx, quality_score=ctx.quality.overall_score)
        if not ctx.quality.passed:
            self._regenerate(ctx)

    def _regenerate(self, ctx: PipelineContext):
        """Bounded regeneration: try fresh hooks/scripts before accepting a fail.

        DESIGN: a failed gate is a business outcome, not a crash. After exhausting
        regenerations we record `quality_failed`, keep the artifact (never lose
        work), and let the run complete — publishing is simply withheld.
        """
        attempts = self.settings.reliability.max_retries
        for i in range(1, attempts + 1):
            log.warning("Quality failed (%s). Regeneration attempt %d/%d.",
                        ctx.quality.reasons, i, attempts)
            self._stage_hook(ctx)
            self._stage_script(ctx)
            self._stage_visual(ctx)
            self._stage_voice(ctx)
            self._stage_video(ctx)
            ctx.quality = self._agent_output("quality", ctx, ctx)
            self._update_content(ctx, quality_score=ctx.quality.overall_score)
            if ctx.quality.passed:
                return
        ctx.extra["quality_failed"] = True
        self._update_content(ctx, status=ContentStatus.QUALITY_FAILED.value)
        log.warning("Quality gate not cleared after %d regenerations; withholding publish "
                    "(artifact kept). Reasons: %s", attempts, ctx.quality.reasons)

    def _stage_approve(self, ctx):
        if ctx.extra.get("quality_failed"):
            return  # already marked quality_failed; CEO withholds approval
        if not self.ceo.approve(ctx.quality):
            ctx.extra["quality_failed"] = True
            self._update_content(ctx, status=ContentStatus.QUALITY_FAILED.value)
            return
        self._update_content(ctx, status=ContentStatus.QUALITY_PASSED.value)

    def _stage_seo(self, ctx):
        ctx.metadata = self._agent_output("seo", ctx, ctx)
        if ctx.metadata:
            self._update_content(ctx, description=ctx.metadata[0].description,
                                 keywords=ctx.metadata[0].tags)

    def _stage_thumbnail(self, ctx):
        title = ctx.script.title if ctx.script else (ctx.topic.angle if ctx.topic else "")
        result = self._agent_output("thumbnail", {
            "title": title, "run_id": ctx.run_id, "content_id": ctx.content_id,
            "video_format": ctx.video_format,
        }, ctx)
        ctx.extra["thumbnails"] = result.get("variants", [])
        ctx.extra["thumbnail"] = result.get("selected")

    def _stage_publish(self, ctx):
        if ctx.extra.get("quality_failed"):
            log.info("Publish skipped for run %s (quality gate not cleared).", ctx.run_id)
            return
        ctx.publish_results = self._agent_output("publishing", ctx, ctx)
        published = any(r.status in ("published", "dry_run") for r in ctx.publish_results)
        if published:
            self._update_content(ctx, status=ContentStatus.PUBLISHED.value,
                                 published_date=datetime.now(timezone.utc))

    def _stage_finalize(self, ctx):
        """Store the Topic DNA in ContentMemory — the learning system's input."""
        with session_scope() as s:
            exists = s.query(ContentMemory).filter(ContentMemory.video_id == ctx.content_id).first()
            if not exists:
                s.add(ContentMemory(
                    video_id=ctx.content_id, topic=ctx.topic.topic,
                    hook=ctx.selected_hook.text if ctx.selected_hook else None,
                    hook_type=ctx.selected_hook.hook_type if ctx.selected_hook else None,
                    story_structure=ctx.script.structure if ctx.script else None,
                    script_style=ctx.script.style if ctx.script else None,
                    duration=ctx.video.duration if ctx.video else None,
                    voice_style=ctx.voice.provider if ctx.voice else None,
                    thumbnail_style="auto",
                    visual_style=self.settings.images.style,
                    performance_score=None,
                ))
            # Mark the topic as used so it isn't re-selected.
            from core.database.models import Topic
            used = s.query(Topic).filter(Topic.angle == ctx.topic.angle).first()
            if used:
                used.status = "used"

    # ── persistence helpers ────────────────────────────────────────────────
    def _update_content(self, ctx: PipelineContext, **fields):
        if ctx.content_id is None:
            return
        with session_scope() as s:
            content = s.get(Content, ctx.content_id)
            if content:
                for k, v in fields.items():
                    setattr(content, k, v)

    # ── checkpointing ──────────────────────────────────────────────────────
    def _checkpoint(self, ctx: PipelineContext):
        if not self.settings.reliability.checkpoint:
            return
        path = self._checkpoint_dir / f"{ctx.run_id}.json"
        path.write_text(ctx.model_dump_json(indent=2), encoding="utf-8")

    def _load_checkpoint(self, run_id: str) -> PipelineContext | None:
        path = self._checkpoint_dir / f"{run_id}.json"
        if not path.exists():
            return None
        return PipelineContext(**json.loads(path.read_text(encoding="utf-8")))


def run_once(category: str | None = None, video_format: str = "short") -> PipelineContext:
    return Orchestrator().produce(category=category, video_format=video_format)
