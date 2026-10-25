"""End-to-end smoke test: the whole DAG runs offline and produces artifacts."""

from pathlib import Path

from core.orchestrator import Orchestrator


def test_full_pipeline_offline_produces_video():
    ctx = Orchestrator().produce(category="psychology", video_format="short")

    # No stage failed.
    assert not ctx.extra.get("failed_stage"), ctx.extra.get("error")

    # Core artifacts exist.
    assert ctx.topic is not None
    assert ctx.selected_hook is not None
    assert ctx.script is not None and ctx.script.word_count > 0
    assert ctx.scene_plan is not None and len(ctx.scene_plan.scenes) > 0
    assert ctx.voice is not None and Path(ctx.voice.audio_path).exists()
    assert ctx.video is not None and Path(ctx.video.video_path).exists()
    assert ctx.quality is not None

    # Reached publish (dry-run) and finalize.
    assert "publish" in ctx.completed_stages
    assert "finalize" in ctx.completed_stages


def test_pipeline_persists_content_and_memory():
    from core.database.models import Content, ContentMemory
    from core.database.session import session_scope

    ctx = Orchestrator().produce(category="history", video_format="short")
    with session_scope() as s:
        content = s.get(Content, ctx.content_id)
        assert content is not None
        # Any terminal status is valid; the point is content + Topic DNA persist.
        assert content.status in ("published", "quality_passed", "quality_failed", "in_review")
        assert content.quality_score is not None
        mem = s.query(ContentMemory).filter_by(video_id=ctx.content_id).first()
        assert mem is not None
        assert mem.hook is not None


def test_learning_loop_over_seeded_analytics():
    """The analytics -> learning -> CEO report loop runs on published content."""
    from datetime import datetime, timezone

    from core.database.models import Content, ContentMemory
    from core.database.session import session_scope
    from core.registry import get_agent, load_all_agents

    load_all_agents()
    with session_scope() as s:
        for i, (cat, hook_type) in enumerate([("psychology", "curiosity"),
                                              ("history", "emotion"),
                                              ("psychology", "curiosity")]):
            c = Content(topic=f"seed {i}", category=cat, title=f"Seed {i}",
                        status="published", quality_score=88.0,
                        published_date=datetime.now(timezone.utc))
            s.add(c)
            s.flush()
            s.add(ContentMemory(video_id=c.id, topic=c.topic, hook=f"hook {i}",
                                hook_type=hook_type, duration=60.0))

    assert get_agent("analytics").execute({}).status == "success"
    learn = get_agent("learning").execute({})
    assert learn.status == "success"
    assert learn.output["insights"]["samples"] == 3
    report = get_agent("ceo").execute({})
    assert report.status == "success"
    assert report.output.summary


def test_failed_text_gate_skips_render():
    """A script that fails facts/originality/hook must never be rendered.

    Before the pre-render gate, quality ran AFTER rendering, so every failure
    cost a full render (minutes at 1440p) and then re-rendered on retry.
    """
    from core.config import get_settings
    from core.database.models import Content
    from core.database.session import session_scope

    q = get_settings().quality
    q.hook_score_min = 101          # impossible: forces the text gate to fail
    ctx = Orchestrator().produce(category="history", video_format="short")

    assert ctx.extra.get("precheck_failed") is True
    assert ctx.video is None and ctx.voice is None      # nothing was rendered
    assert "precheck" in ctx.completed_stages
    with session_scope() as s:
        assert s.get(Content, ctx.content_id).status == "quality_failed"


def test_passing_text_gate_still_renders():
    ctx = Orchestrator().produce(category="psychology", video_format="short")
    assert ctx.extra.get("precheck", {}).get("passed") is True
    assert ctx.video is not None


def test_topic_agent_honours_exclusions():
    from core.registry import get_agent, load_all_agents
    load_all_agents()
    agent = get_agent("topic")
    first = agent.execute({"category": "history", "trends": []}).output
    second = agent.execute({"category": "history", "trends": [],
                            "exclude": [first.topic, first.angle]}).output
    assert second.topic.lower() != first.topic.lower()
