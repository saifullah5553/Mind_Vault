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


def test_hook_and_title_cleaners_strip_labels_and_quotes():
    from agents.hook_engine.agent import _clean_line
    assert _clean_line('Hook 8: "Revealed: the hidden reason."') == "Revealed: the hidden reason."
    assert _clean_line("- 3) The Secret of Rome") == "The Secret of Rome"
    assert _clean_line('"A quoted hook"') == "A quoted hook"

    from core.registry import get_agent
    seo = get_agent("seo")
    assert seo._clean_title('2. "The Untold Story"') == "The Untold Story"
    assert seo._clean_title("The Fall of Rome") == "The Fall of Rome"


def test_srt_captions_generated_from_scenes():
    from core.media.captions import build_srt
    from core.schemas import Scene
    scenes = [Scene(index=0, narration="First line.", visual_prompt="x", duration=3.0),
              Scene(index=1, narration="Second line.", visual_prompt="y", duration=2.5)]
    path = build_srt(scenes, "storage/audio/_test.srt")
    assert path and Path(path).exists()
    body = Path(path).read_text(encoding="utf-8")
    assert "00:00:00,000 --> 00:00:03,000" in body
    assert "First line." in body and "Second line." in body


def test_publishers_gated_without_credentials(monkeypatch):
    from core.publishing import get_publisher, publisher_status
    # Ensure no creds in env for this test.
    for k in ("YOUTUBE_CLIENT_ID", "FACEBOOK_PAGE_ID", "TIKTOK_ACCESS_TOKEN", "INSTAGRAM_USER_ID"):
        monkeypatch.delenv(k, raising=False)
    status = publisher_status()
    assert set(status) == {"youtube", "facebook", "tiktok", "instagram"}
    assert all(not v["configured"] for v in status.values())
    yt = get_publisher("youtube")
    assert not yt.is_configured()
    assert "YOUTUBE_CLIENT_ID" in yt.missing_env()


def test_publishing_agent_dry_run_by_default():
    from core.registry import get_agent, load_all_agents
    from core.schemas import PipelineContext, PlatformMetadata, VideoResult
    load_all_agents()
    ctx = PipelineContext(run_id="pubtest", category="history")
    ctx.video = VideoResult(video_path="storage/videos/nope.mp4", duration=60,
                            resolution=[1080, 1920], engine="gif")
    ctx.metadata = [PlatformMetadata(platform="youtube", title="T", description="D"),
                    PlatformMetadata(platform="tiktok", title="T", description="D")]
    res = get_agent("publishing").execute(ctx).output
    assert {r.platform for r in res} == {"youtube", "tiktok"}
    # dry_run is true by default -> nothing actually posts.
    assert all(r.status == "dry_run" for r in res)


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
