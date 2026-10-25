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


def _count_documentary_calls(monkeypatch) -> list:
    from core.registry import get_agent, load_all_agents
    load_all_agents()
    cls = type(get_agent("documentary"))
    calls, real = [], cls.run

    def counting(self, payload):
        calls.append(1)
        return real(self, payload)

    monkeypatch.setattr(cls, "run", counting)
    return calls


def test_weak_hook_without_better_option_keeps_documentary(monkeypatch):
    """Re-writing ~1,700 words can't raise a hook score; don't do it."""
    from core.config import get_settings
    get_settings().quality.hook_score_min = 101
    calls = _count_documentary_calls(monkeypatch)
    ctx = Orchestrator().produce(category="history", video_format="long")
    assert ctx.extra.get("precheck_failed") is True
    assert len(calls) == 1


def test_stronger_hook_is_spliced_into_documentary_intro(monkeypatch):
    from core.config import get_settings
    get_settings().quality.hook_score_min = 101
    orch = Orchestrator()
    ctx = orch.produce(category="history", video_format="long")
    old = ctx.selected_hook
    chapters_before = ctx.script.body
    calls = _count_documentary_calls(monkeypatch)

    better = old.model_copy(update={"text": "A brand new opening line.",
                                    "total": old.total + 5})
    monkeypatch.setattr(orch, "_stage_hook",
                        lambda c: setattr(c, "selected_hook", better))
    orch._rehook(ctx)

    assert calls == []                                   # no chapter rewrite
    assert ctx.selected_hook.text == better.text
    assert ctx.script.introduction.startswith(better.text)
    assert ctx.script.full_text.count(better.text) == 1
    assert old.text not in ctx.script.full_text
    assert ctx.script.body == chapters_before


def test_resilient_llm_counts_fallbacks_and_keeps_native_json():
    from core.errors import ProviderError
    from core.llm import factory
    from core.llm.stub_provider import StubLLM

    class Down:
        name = "down"
        def generate(self, *a, **k): raise ProviderError("offline")
        def generate_json(self, *a, **k): raise ProviderError("offline")

    class JsonOnly:
        name = "json"
        def generate(self, *a, **k): raise AssertionError("must use native JSON mode")
        def generate_json(self, *a, **k): return {"ok": True}

    assert factory.ResilientLLM(JsonOnly(), StubLLM()).generate_json([]) == {"ok": True}
    before = factory.fallback_count()
    factory.ResilientLLM(Down(), StubLLM()).generate([])
    try:
        factory.ResilientLLM(Down(), StubLLM()).generate_json([])
    except ValueError:
        pass  # the stub has no JSON to give for an empty prompt; only the count matters
    assert factory.fallback_count() == before + 2


def _fallback_during_script(monkeypatch, times: int):
    """Pretend the first `times` script-writing calls fell back to the stub."""
    import core.orchestrator as orch_mod
    from core.registry import get_agent, load_all_agents
    load_all_agents()
    counter = {"n": 0, "left": times}
    cls = type(get_agent("script"))
    real = cls.run

    def run(self, payload):
        if counter["left"] > 0:
            counter["left"] -= 1
            counter["n"] += 1
        return real(self, payload)

    monkeypatch.setattr(cls, "run", run)
    monkeypatch.setattr(orch_mod, "fallback_count", lambda: counter["n"])


def test_stub_written_script_is_never_rendered(monkeypatch):
    _fallback_during_script(monkeypatch, times=99)
    ctx = Orchestrator().produce(category="history", video_format="short")
    assert ctx.extra.get("precheck_failed") is True
    assert any("llm_fallback" in r for r in ctx.extra["precheck"]["reasons"])
    assert ctx.video is None and ctx.voice is None


def test_one_off_fallback_is_rewritten_then_rendered(monkeypatch):
    _fallback_during_script(monkeypatch, times=1)
    ctx = Orchestrator().produce(category="history", video_format="short")
    assert ctx.extra["precheck"]["passed"] is True
    assert ctx.video is not None
