"""Live publishing + analytics plumbing, with every Google call mocked."""

import json
from datetime import datetime, timezone

import httpx
import pytest

from core.database.models import Analytics, Content, ContentMemory, PlatformPost
from core.database.session import session_scope
from core.registry import get_agent, load_all_agents


class _Resp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body or {}, headers or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)


def _published(with_post: bool, title="Live one") -> int:
    with session_scope() as s:
        c = Content(topic=title, category="history", title=title, status="published",
                    quality_score=80.0, published_date=datetime.now(timezone.utc))
        s.add(c)
        s.flush()
        s.add(ContentMemory(video_id=c.id, topic=title, hook_type="curiosity", duration=60))
        if with_post:
            s.add(PlatformPost(content_id=c.id, platform="youtube",
                               external_id="abc123", url="https://youtu.be/abc123"))
        return c.id


# ── YouTube Analytics client ────────────────────────────────────────────────
def test_video_report_maps_documented_metrics(monkeypatch):
    from core.analytics import youtube as yta

    def fake_get(url, headers, params, timeout):
        assert params["ids"] == "channel==MINE" and params["filters"] == "video==abc123"
        if params.get("dimensions") == "elapsedVideoTimeRatio":
            return _Resp(body={"rows": [[i / 100, 1 - i / 200] for i in range(1, 101)]})
        cols = ["views", "estimatedMinutesWatched", "averageViewDuration",
                "averageViewPercentage", "likes", "comments", "shares", "subscribersGained"]
        return _Resp(body={"columnHeaders": [{"name": c} for c in cols],
                           "rows": [[1200, 900, 45.0, 62.5, 80, 9, 4, 12]]})

    monkeypatch.setattr(yta.httpx, "get", fake_get)
    r = yta.video_report("abc123", token="t")
    assert r["views"] == 1200 and r["retention"] == 62.5
    assert r["watch_time"] == 15.0            # 900 minutes -> hours
    assert r["ctr"] == 0.0                    # not available from the API: never guessed
    assert len(r["retention_curve"]) == 10
    assert r["retention_curve"][0] > r["retention_curve"][-1]


# ── Analytics agent ─────────────────────────────────────────────────────────
def test_auto_mode_never_invents_numbers():
    load_all_agents()
    _published(with_post=False)
    out = get_agent("analytics").execute({}).output
    assert out["simulated_rows"] == 0 and out["rows"] == 0
    with session_scope() as s:
        assert s.query(Analytics).count() == 0
        assert s.query(ContentMemory).first().performance_score is None


def test_live_row_for_real_upload(monkeypatch):
    load_all_agents()
    for k in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"):
        monkeypatch.setenv(k, "x")
    import core.analytics.youtube as yta
    monkeypatch.setattr(yta, "video_report", lambda vid, published, deciles=10: {
        "views": 500, "ctr": 0.0, "avg_view_duration": 30.0, "watch_time": 2.0,
        "retention": 55.0, "retention_curve": [100, 50], "completion_rate": 50.0,
        "likes": 5, "comments": 1, "shares": 0, "subscribers_generated": 2})
    cid = _published(with_post=True)
    out = get_agent("analytics").execute({}).output
    assert out["live_rows"] == 1 and out["simulated_rows"] == 0
    with session_scope() as s:
        row = s.query(Analytics).one()
        assert row.video_id == cid and row.platform == "youtube" and row.views == 500
        assert s.query(ContentMemory).first().performance_score == 55.0


def test_learning_ignores_unmeasured_videos():
    load_all_agents()
    _published(with_post=False)
    learn = get_agent("learning").execute({}).output
    assert learn["insights"]["samples"] == 0


# ── Publishing ──────────────────────────────────────────────────────────────
def test_real_upload_is_recorded_for_analytics(monkeypatch):
    from core.schemas import PipelineContext, PlatformMetadata, PublishResult, VideoResult
    load_all_agents()
    cid = _published(with_post=False)
    agent = get_agent("publishing")
    monkeypatch.setattr(type(agent), "_dispatch", lambda self, pkg, dry: PublishResult(
        platform="youtube", status="published", url="https://youtu.be/zz9", external_id="zz9"))
    ctx = PipelineContext(run_id="live1", category="history", content_id=cid)
    ctx.video = VideoResult(video_path="v.mp4", duration=60, resolution=[1920, 1080], engine="x")
    ctx.metadata = [PlatformMetadata(platform="youtube", title="T", description="D")]
    agent.execute(ctx)
    with session_scope() as s:
        post = s.query(PlatformPost).one()
        assert (post.content_id, post.external_id) == (cid, "zz9")


def test_chunked_upload_resumes_after_server_error(monkeypatch, tmp_path):
    from core.publishing import youtube as yt
    monkeypatch.setattr(yt, "_CHUNK", 4)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"0123456789")                 # 10 bytes -> chunks of 4
    held = {"n": 0}
    calls = []

    def fake_put(url, content, timeout, headers):
        calls.append(headers["Content-Range"])
        if headers["Content-Range"].startswith("bytes */"):        # status query
            return _Resp(308, headers={"Range": f"bytes=0-{held['n'] - 1}"})
        if len(calls) == 2:
            return _Resp(503)                                       # transient failure
        held["n"] += len(content)
        if held["n"] >= 10:
            return _Resp(200, body={"id": "vid42"})
        return _Resp(308, headers={"Range": f"bytes=0-{held['n'] - 1}"})

    monkeypatch.setattr(yt.httpx, "put", fake_put)
    assert yt._upload_chunks("https://session", video, sleep=lambda s: None) == {"id": "vid42"}
    assert calls == ["bytes 0-3/10", "bytes 4-7/10", "bytes */10", "bytes 4-7/10", "bytes 8-9/10"]


def test_caption_metadata_is_json(monkeypatch, tmp_path):
    from core.publishing import youtube as yt
    srt = tmp_path / "c.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHi\n", encoding="utf-8")
    seen = {}

    def fake_post(url, params, headers, files, timeout):
        seen["params"], seen["meta"] = params, json.loads(files["metadata"][1])
        return _Resp(200)

    monkeypatch.setattr(yt.httpx, "post", fake_post)
    yt.YouTubePublisher()._upload_caption("vid42", str(srt), "tok")
    assert seen["meta"]["snippet"]["videoId"] == "vid42"
    assert seen["params"]["uploadType"] == "multipart"


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """Belt and braces: any unmocked Google call fails the test loudly."""
    def boom(*a, **k):
        raise AssertionError("unexpected real network call")
    import core.publishing.youtube as yt
    monkeypatch.setattr(yt, "access_token", boom)
