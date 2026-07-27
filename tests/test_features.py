"""Tests for the prompt system, thumbnail engine, and content calendar."""

from pathlib import Path

from core.calendar import build_calendar
from core.prompts import render
from core.registry import get_agent, load_all_agents


def test_prompt_render_uses_template_and_marker():
    out = render("hooks", topic="fear", category="psychology")
    assert "TASK: hooks" in out          # marker preserved (routes the stub)
    assert "fear" in out                  # variable substituted


def test_prompt_render_missing_template_fallback():
    out = render("nonexistent_task", topic="x", category="y")
    assert out.startswith("TASK: nonexistent_task")
    assert "TOPIC: x" in out


def test_thumbnail_agent_creates_variants():
    load_all_agents()
    from core.database.models import Content, Thumbnail
    from core.database.session import session_scope
    with session_scope() as s:
        c = Content(topic="t", category="history", title="The Secret History of Rome",
                    status="produced")
        s.add(c)
        s.flush()
        cid = c.id

    res = get_agent("thumbnail").execute(
        {"title": "The Secret History of Rome", "run_id": "tst", "content_id": cid,
         "video_format": "short"})
    assert res.status == "success"
    variants = res.output["variants"]
    assert len(variants) >= 1
    assert all(Path(p).exists() for p in variants)
    with session_scope() as s:
        assert s.query(Thumbnail).filter_by(content_id=cid).count() == len(variants)
        assert s.query(Thumbnail).filter_by(content_id=cid, selected=True).count() == 1


def test_presenter_generates_consistent_portrait():
    load_all_agents()
    from core.schemas import VoiceResult
    # Give it a real (silent) audio file so the agent path runs fully.
    from core.media.tts import synthesize_speech
    voice = synthesize_speech("Hello from the presenter.", "storage/audio/_pres_test.wav")
    res = get_agent("presenter").execute({"voice": voice, "run_id": "prestest"})
    assert res.status == "success"
    out = res.output
    assert out["persona"]                      # a named persona
    assert out["disclosure"]                   # AI disclosure present
    assert out["portrait"] and Path(out["portrait"]).exists()   # synthetic face made
    # overlay defaults to the portrait when no GPU lip-sync clip was produced
    assert out["overlay"] == out["portrait"] or out["clip"]


def test_seo_includes_presenter_disclosure():
    load_all_agents()
    from core.schemas import PipelineContext, ScoredTopic
    ctx = PipelineContext(run_id="seotest", category="history")
    ctx.topic = ScoredTopic(topic="rome", category="history", angle="The Fall of Rome")
    ctx.extra["presenter"] = {"disclosure": "Narrated by Aria, an AI-generated presenter."}
    metas = get_agent("seo").execute(ctx).output
    assert metas
    assert all("AI-generated presenter" in m.description for m in metas)


def test_ollama_availability_is_graceful_when_absent():
    from core.llm.ollama_provider import OllamaLLM
    o = OllamaLLM(model="llama3.1")
    # No server running in tests -> must not raise, just report unavailable.
    assert o.is_available() in (True, False)
    assert isinstance(o.installed_models(), list)


def test_doctor_runs_without_error():
    import scripts.doctor as doc
    for fn in (doc._check_ollama, doc._check_voice, doc._check_gpu,
               doc._check_video, doc._check_presenter):
        out = fn()
        assert isinstance(out, list) and out  # each returns report lines


def test_calendar_balances_and_avoids_repeats():
    from datetime import date
    cal = build_calendar(start=date(2026, 1, 1), days=42)
    assert len(cal) > 0
    cats = {e["category"] for e in cal}
    assert cats.issubset({"psychology", "history"})
    # both categories represented over 6 weeks
    assert len(cats) == 2
    # no immediate subcategory repeat
    for a, b in zip(cal, cal[1:]):
        assert not (a["subcategory"] == b["subcategory"] and a["category"] == b["category"])
