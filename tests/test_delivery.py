"""Expressive narration, the 10-minute limit, credits, chapters and uploaders."""

import json
from pathlib import Path

import httpx
import numpy as np
import pytest

from core.config import get_settings
from core.media import credits
from core.media.delivery import Delivery, perform, plan
from core.media.spoken import sentences
from core.media.tts import _say


def test_delivery_follows_the_meaning_of_the_line():
    assert plan("Why does that happen, in the end?").end > 0          # questions lift
    assert plan("And slowly, the fire went out for all of them here today.").end < 0
    dark, bright = plan("They got worse, and everyone involved was lost."), \
        plan("They loved every moment and enjoyed it all very much indeed.")
    assert dark.pitch < 0 < bright.pitch
    assert dark.rate > bright.rate                                   # heavy lines move slower
    punch = plan("It's reward.")
    assert punch.pause_after >= 0.45 and punch.rate > 1
    heading = plan("Chapter two: The Turning Point.")
    assert heading.pause_before > 0.5 and heading.pause_after > 0.5
    assert plan("But the danger is narrower than that, and more personal.").pause_before > 0
    assert plan("Same line twice.") == plan("Same line twice.")       # repeatable renders


def test_pitch_shaping_raises_the_end_of_a_question():
    sr = 22050
    t = np.arange(sr, dtype="float32") / sr
    tone = np.sin(2 * np.pi * 200 * t).astype("float32")
    y = perform(tone, sr, Delivery(pitch=0.0, end=3.0))

    def freq(x):
        spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
        return np.argmax(spec) * sr / len(x)

    assert freq(y[-2500:]) > freq(y[:2500]) * 1.05


def test_years_are_read_as_years():
    assert _say("In 1898, a study.", {}) == "In eighteen ninety eight, a study."
    assert "nineteen forties" in _say("In the 1940s.", {})
    assert "nineteen oh five" in _say("By 1905.", {})
    assert "two thousand" in _say("In 2000.", {})
    assert _say("Edward Deci.", {"Deci": "Deesee"}) == "Edward Deesee."


def test_scenes_cut_exactly_on_the_voice():
    from core.registry import get_agent, load_all_agents
    from core.schemas import Scene, ScenePlan, VoiceResult
    load_all_agents()
    plan_ = ScenePlan(scenes=[
        Scene(index=0, narration="One. Two.", visual_prompt="x", duration=3, sentences=2),
        Scene(index=1, narration="Three.", visual_prompt="x", duration=3)])
    segs = [{"text": "One.", "start": 0.25, "end": 1.5}, {"text": "Two.", "start": 1.5, "end": 4.0},
            {"text": "Three.", "start": 4.0, "end": 9.0}]
    voice = VoiceResult(audio_path="a.wav", duration=9.0, provider="piper", voice="Aria",
                        segments=segs)
    get_agent("video")._match_narration(plan_, voice)
    assert [s.duration for s in plan_.scenes] == [4.0, 5.0]


def test_visual_plan_groups_short_lines_and_keeps_every_sentence():
    from core.registry import get_agent, load_all_agents
    from core.script_file import load
    load_all_agents()
    script, head = load("content/scripts/motivation_documentary.txt")
    assert head["thumbnail"] == "REWARDS KILL PASSION"
    plan_ = get_agent("visual").run({"script": script})
    from core.media.spoken import spoken_text
    assert sum(s.sentences for s in plan_.scenes) == len(sentences(spoken_text(script.full_text)))
    chapters = [s for s in plan_.scenes if s.narration.startswith("Chapter ")]
    assert len(chapters) == 5 and all(s.sentences == 1 for s in chapters)


def test_no_script_may_run_over_ten_minutes():
    from core.orchestrator import Orchestrator
    from core.registry import get_agent, load_all_agents
    from core.schemas import PipelineContext, Script
    load_all_agents()
    long_text = "word " * 1400
    ctx = PipelineContext(run_id="x", category="history")
    ctx.script = Script(title="t", hook="h", introduction="", body="", ending="", cta="",
                        full_text=long_text, word_count=1400)
    reasons, _ = get_agent("quality").precheck(ctx)
    assert any(r.startswith("too_long") for r in reasons)
    assert get_settings().formats.long.duration_seconds[1] < 600
    # The generator's own budget stays under the limit at the performed pace.
    words = 1150
    assert words / get_settings().quality.narration_wpm * 60 < 600
    ctx2 = Orchestrator().produce(category="history", video_format="long")
    assert ctx2.script.word_count <= 1300


def test_documentary_chapters_are_trimmed_to_budget():
    from core.registry import get_agent, load_all_agents
    load_all_agents()
    doc = get_agent("documentary")
    assert len(doc._trim("One two three. Four five six. Seven eight nine.", 6).split()) == 6


def test_credits_keep_what_licences_require(tmp_path):
    items = [{"title": "Sunrise.jpg", "credit": "<b>Ana</b>\n Silva", "license": "CC BY-SA 4.0",
              "source": "Wikimedia Commons", "page": "https://commons.wikimedia.org/wiki/File:S"},
             {"title": "Old map.jpg", "credit": "", "license": "Public domain",
              "source": "Wikimedia Commons", "page": ""},
             {"title": "city", "credit": "bob", "license": "Pixabay Content License",
              "source": "Pixabay", "page": ""}]
    credits.add(tmp_path, items[:2], "image")
    credits.add(tmp_path, items[2:], "footage")
    credits.add(tmp_path, items[:1], "image")                # no duplicates
    used = credits.load(tmp_path)
    assert len(used) == 3
    text = credits.block(used, 500)
    assert "Sunrise by Ana Silva (CC BY-SA 4.0" in text and "commons.wikimedia.org" in text
    assert "Old map" not in text and "free-licence material from" in text
    tight = credits.block(used, 90)                          # links dropped, author kept
    assert "Ana Silva" in tight and len(tight) <= 90
    credits.reset(tmp_path)
    assert credits.load(tmp_path) == []


def test_description_has_chapters_and_credits_but_no_internal_notes(tmp_path):
    from core.orchestrator import Orchestrator
    ctx = Orchestrator().produce(category="history", video_format="long")
    assert ctx.metadata
    for m in ctx.metadata:
        assert "[optimized for" not in m.description
    yt = next(m for m in ctx.metadata if m.platform == "youtube")
    assert "0:00 Introduction" in yt.description


def test_chapter_list_needs_three_real_chapters():
    from core.registry import get_agent, load_all_agents
    from core.schemas import PipelineContext, Scene, ScenePlan
    load_all_agents()
    seo = get_agent("seo")

    def scene(i, text, d):
        return Scene(index=i, narration=text, visual_prompt="x", duration=d)

    ctx = PipelineContext(run_id="x", category="history")
    ctx.scene_plan = ScenePlan(scenes=[scene(0, "Intro.", 65), scene(1, "Chapter one: A.", 70),
                                       scene(2, "Chapter two: B.", 30)])
    assert seo._chapters(ctx) == "0:00 Introduction\n1:05 A\n2:15 B"
    ctx.scene_plan.scenes[0].duration = 5                    # under YouTube's 10 s minimum
    assert seo._chapters(ctx) == ""


def test_captions_use_the_script_not_what_was_misheard():
    from core.media.captions import align_to_script
    from core.media.transcribe import Word
    heard = [Word("Edward", 0.0, 0.4), Word("Dessie", 0.4, 0.9), Word("ran", 0.9, 1.2),
             Word("the", 1.2, 1.3), Word("study.", 1.3, 1.8)]
    words = align_to_script(heard, "Edward Deci ran the study.")
    assert [w.text for w in words] == ["Edward", "Deci", "ran", "the", "study."]
    assert words[1].start == pytest.approx(0.4) and words[-1].end == pytest.approx(1.8)


def test_documentaries_and_clips_go_to_the_right_platforms():
    from core.registry import get_agent, load_all_agents
    from core.schemas import PipelineContext, PlatformMetadata, VideoResult
    load_all_agents()
    ctx = PipelineContext(run_id="pubfmt", category="history", video_format="long")
    ctx.video = VideoResult(video_path="v.mp4", duration=500, resolution=[2560, 1440], engine="x")
    ctx.metadata = [PlatformMetadata(platform=p, title="T", description="D")
                    for p in ("youtube", "tiktok", "facebook")]
    res = get_agent("publishing").execute(ctx).output
    assert {r.platform for r in res} == {"youtube", "facebook"}


def test_review_bundle_lists_claims_to_verify(tmp_path):
    from core.registry import get_agent, load_all_agents
    load_all_agents()
    out = tmp_path / "claims.txt"
    get_agent("review")._write_claims(
        "[INTRODUCTION]\nA plain line.\n\n[CHAPTER: One]\nIn 1971, Edward Deci paid students.", out)
    text = out.read_text(encoding="utf-8")
    assert "Edward Deci" in text and "A plain line" not in text and "Chapter one" not in text


# ── uploaders (all network mocked) ──────────────────────────────────────────
class _Resp:
    def __init__(self, status=200, body=None, text=""):
        self.status_code, self._body, self.text = status, body or {}, text

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)


def test_tiktok_chunks_follow_the_documented_rules():
    from core.publishing.tiktok import chunk_ranges, plan_chunks
    assert plan_chunks(4_000_000) == (4_000_000, 1)
    size = 1_047_463_994
    chunk, total = plan_chunks(size)
    assert 5 * 2**20 <= chunk <= 64 * 2**20 and total == size // chunk and total <= 1000
    ranges = chunk_ranges(size, chunk, total)
    assert ranges[0][0] == 0 and ranges[-1][1] == size - 1
    assert all(b[0] == a[1] + 1 for a, b in zip(ranges, ranges[1:]))
    assert ranges[-1][1] - ranges[-1][0] + 1 <= 128 * 2**20


def test_tiktok_refuses_a_video_over_the_creators_limit(monkeypatch, tmp_path):
    from core.publishing import tiktok
    from core.schemas import PublishPackage
    monkeypatch.setenv("TIKTOK_ACCESS_TOKEN", "t")
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x" * 10)
    monkeypatch.setattr(tiktok.httpx, "post", lambda *a, **k: _Resp(body={"data": {
        "max_video_post_duration_sec": 180, "privacy_level_options": ["SELF_ONLY"]}}))
    pkg = PublishPackage(platform="tiktok", video_path=str(v), title="T", description="D",
                         duration=500.0)
    assert tiktok.TikTokPublisher().publish(pkg).status == "failed"


def test_facebook_stays_unpublished_unless_public(monkeypatch, tmp_path):
    from core.publishing import facebook
    from core.schemas import PublishPackage
    for k in ("FACEBOOK_APP_ID", "FACEBOOK_USER_TOKEN", "FACEBOOK_PAGE_ID", "FACEBOOK_PAGE_TOKEN"):
        monkeypatch.setenv(k, "x")
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x" * 10)
    seen = {}
    monkeypatch.setattr(facebook, "upload_file", lambda *a, **k: "handle")

    def post(url, timeout, data):
        seen.update(data)
        return _Resp(body={"id": "vid1"})

    monkeypatch.setattr(facebook.httpx, "post", post)
    pkg = PublishPackage(platform="facebook", video_path=str(v), title="T", description="D",
                         privacy="private")
    res = facebook.FacebookPublisher().publish(pkg)
    assert seen["published"] == "false" and seen["fbuploader_video_file_chunk"] == "handle"
    assert res.external_id == "vid1"


def test_facebook_upload_resumes_from_the_reported_offset(monkeypatch, tmp_path):
    from core.publishing import facebook
    v = tmp_path / "v.mp4"
    v.write_bytes(b"0123456789")
    calls = []

    def post(url, **kw):
        if "uploads" in url:
            return _Resp(body={"id": "upload:abc"})
        calls.append(kw["headers"]["file_offset"])
        body = b"".join(kw["content"])
        if len(calls) == 1:
            return _Resp(status=503)
        assert body == b"456789"
        return _Resp(body={"h": "handle"})

    monkeypatch.setattr(facebook.httpx, "post", post)
    monkeypatch.setattr(facebook.httpx, "get", lambda *a, **k: _Resp(body={"file_offset": 4}))
    assert facebook.upload_file(v, "app", "tok", sleep=lambda s: None) == "handle"
    assert calls == ["0", "4"]


def test_upload_pack_keeps_each_video_on_its_platforms(monkeypatch, tmp_path):
    from core.config import ROOT_DIR
    from scripts import upload_pack
    s = get_settings()
    bundle = ROOT_DIR / s.publishing.review_dir / "packtest"
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "video.mp4").write_bytes(b"v")
    (bundle / "thumbnail.png").write_bytes(b"t")
    (bundle / "review.json").write_text(json.dumps({"title": "A Title: Here", "format": "long"}))
    (bundle / "metadata.json").write_text(json.dumps([
        {"platform": "youtube", "title": "T", "description": "D", "tags": ["a"], "hashtags": ["#x"]},
        {"platform": "tiktok", "title": "T", "description": "D", "tags": [], "hashtags": []}]))
    out = upload_pack.build("packtest", tmp_path)
    assert (out / "youtube" / "video.mp4").exists()
    assert (out / "youtube" / "description.txt").read_text(encoding="utf-8").startswith("D")
    assert not (out / "tiktok").exists()


def test_lines_show_what_they_are_about():
    from core.media.themes import subject_of
    assert subject_of("The cats escaped.") == "cat"
    assert subject_of("Then the money stopped.") == "money cash"
    assert subject_of("Children who loved drawing were promised an award.").startswith("child drawing")
    assert subject_of("A plain line about nothing concrete.") is None


def test_concrete_lines_get_their_own_shots(monkeypatch, tmp_path):
    from core.registry import get_agent, load_all_agents
    from core.schemas import Scene
    load_all_agents()
    agent = get_agent("video")
    monkeypatch.setattr("core.media.stock_video.fetch_subject_clips", lambda wanted, *a, **k: {
        q: [{"path": f"{q}{i}.mp4", "url": f"{q}{i}", "title": "t", "source": "Pixabay",
             "license": "x"} for i in range(n)] for q, n in wanted.items()})
    scenes = [Scene(index=i, narration=t, visual_prompt="x", duration=3)
              for i, t in enumerate(["The cats escaped.", "A plain line.", "More cats here.",
                                     "One.", "Two.", "Three."])]
    rest = agent._attach_subject_clips(scenes, tmp_path, (640, 360))
    assert [s.clip_path for s in scenes[:4]] == ["cat0.mp4", "cat1.mp4", "cat2.mp4", "cat3.mp4"]
    assert scenes[4].clip_path == "cat4.mp4" and rest == [scenes[5]]


def test_title_card_keeps_its_last_line():
    from PIL import Image, ImageDraw

    from core.media.animation import _fit_text, _font
    d = ImageDraw.Draw(Image.new("RGB", (2560, 1440)))
    text = "The shocking truth about why people stop pursuing their passions"
    _f, wrapped = _fit_text(d, text, lambda s: _font(s, True), int(2560 * 0.84), int(2560 * 0.09),
                            max_h=int(1440 * 0.62), spacing=12)
    assert wrapped.replace("\n", " ") == text


def test_credits_link_to_the_full_list():
    used = [{"title": "A", "author": "B", "license": "CC BY 4.0", "source": "Wikimedia Commons",
             "page": "", "kind": "image"}]
    text = credits.block(used, 500, "https://example.org/run.txt")
    assert text.endswith("Full credits with source links: https://example.org/run.txt")


@pytest.mark.parametrize("licence", [
    "http://creativecommons.org/licenses/by-nc-nd/3.0/",
    "https://creativecommons.org/licenses/by-nc/4.0/",
    "https://creativecommons.org/licenses/by-nd/2.0/",
    "https://creativecommons.org/licenses/by-nc-sa/4.0/",
    "CC BY-NC 4.0", "cc-by-nd", "Non-commercial use only", "All rights reserved",
])
def test_restricted_licences_are_refused(licence):
    from core.media.stock_video import _is_clearable

    assert credits.is_restricted(licence)
    assert _is_clearable({"licenseurl": licence}) == (False, "")
    # A curated collection doesn't override the item's own licence.
    assert _is_clearable({"licenseurl": licence, "collection": ["prelinger"]}) == (False, "")


@pytest.mark.parametrize("licence", [
    "http://creativecommons.org/licenses/by/3.0/",
    "https://creativecommons.org/licenses/by-sa/4.0/",
    "http://creativecommons.org/licenses/publicdomain/",
    "https://creativecommons.org/publicdomain/zero/1.0/",
])
def test_open_licences_still_pass(licence):
    from core.media.stock_video import _is_clearable

    assert not credits.is_restricted(licence)
    assert _is_clearable({"licenseurl": licence})[0]


def test_film_trailers_are_refused_even_if_tagged_public_domain():
    from core.media.stock_video import _is_clearable

    meta = {"licenseurl": "http://creativecommons.org/licenses/publicdomain/"}
    assert not _is_clearable({**meta, "title": 'Movie Trailers: "Marathon of Fright"'})[0]
    assert not _is_clearable({**meta, "collection": ["movie_trailers"]})[0]


def test_commons_photo_without_a_licence_is_skipped(monkeypatch):
    from core.media import stock

    def page(lic):
        return {"title": f"File:{lic or 'none'}.jpg", "imageinfo": [{
            "url": "https://example.org/a.jpg", "width": 4000,
            "extmetadata": {"LicenseShortName": {"value": lic}} if lic else {}}]}

    pages = {"1": page("CC BY-SA 4.0"), "2": page(""), "3": page("CC BY-NC 4.0")}
    reply = httpx.Response(200, json={"query": {"pages": pages}},
                           request=httpx.Request("GET", "https://commons.wikimedia.org/"))
    monkeypatch.setattr(httpx, "get", lambda *a, **k: reply)
    assert [h["license"] for h in stock._commons_search("anything")] == ["CC BY-SA 4.0"]


def test_upload_pack_refuses_a_restricted_credit(tmp_path, monkeypatch):
    from scripts import upload_pack

    bundle = tmp_path / "storage" / "review" / "abc"
    bundle.mkdir(parents=True)
    (bundle / "review.json").write_text("{}", encoding="utf-8")
    (bundle / "metadata.json").write_text("[]", encoding="utf-8")
    credits.add(bundle, [{"title": "Climb talk", "license": "by-nc-nd/3.0",
                          "source": "Internet Archive"}], "footage")
    monkeypatch.setattr(upload_pack, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(upload_pack, "get_settings", lambda: type("S", (), {
        "publishing": type("P", (), {"review_dir": "storage/review"})()})())
    with pytest.raises(SystemExit, match="Climb talk"):
        upload_pack.build("abc", tmp_path / "out")


def test_the_most_specific_subject_wins():
    from core.media.themes import subject_of

    assert subject_of("A researcher put hungry cats inside wooden boxes.") == "cat"
    assert subject_of("To reach the food outside, a cat had to work a latch.") == "cat"
    assert subject_of("The students who were never paid kept playing.").startswith("students")
    assert subject_of("Researchers studied the effect.").startswith("laboratory")


def test_a_line_keeps_the_story_subject_for_a_moment():
    from core.media.themes import carry_subjects

    lines = ["The monkeys solved it.", "They got faster.", "They got better.", "And on.", "Cats."]
    assert carry_subjects(lines) == ["monkey", "monkey", "monkey", None, "cat"]


def test_the_motivation_script_is_mostly_covered():
    from core.media.spoken import sentences
    from core.media.themes import carry_subjects

    text = Path("content/scripts/motivation_documentary.txt").read_text(encoding="utf-8")
    subjects = carry_subjects([s for s, _ in sentences(text)])
    assert sum(1 for s in subjects if s) / len(subjects) > 0.75


def _pixabay_reply(videos):
    return httpx.Response(200, json={"hits": [
        {"tags": "cat", "duration": 20, "user": "u", "pageURL": "p", "videos": videos}]},
        request=httpx.Request("GET", "https://pixabay.com/api/videos/"))


def test_vertical_video_can_crop_big_landscape_clips(monkeypatch):
    from core.media.stock_video import _pixabay_clips

    monkeypatch.setenv("PIXABAY_API_KEY", "x")
    big = {"large": {"url": "u4k", "width": 3840, "height": 2160}}
    small = {"large": {"url": "u1080", "width": 1920, "height": 1080}}
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _pixabay_reply(big))
    assert _pixabay_clips("cat", 1, landscape=False)[0]["url"] == "u4k"
    # 1080p would be upscaled 1.78x after the crop: too soft.
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _pixabay_reply(small))
    assert _pixabay_clips("cat", 1, landscape=False) == []


def test_psychology_footage_never_searches_the_archive(monkeypatch, tmp_path):
    from core.media import stock_video

    called = []
    monkeypatch.setattr(stock_video, "_ia_clips", lambda *a, **k: called.append(a) or [])
    for name in ("_pexels_clips", "_pixabay_clips", "_commons_clips"):
        monkeypatch.setattr(stock_video, name, lambda *a, **k: [])
    stock_video.fetch_clip_pool("motivation", 4, tmp_path, category="psychology")
    assert not called


def test_adult_reels_are_screened_out():
    from core.media.stock_video import acceptable_title

    assert not acceptable_title("Stripper - Sandra Storm")
    assert not acceptable_title("Burlesque dancer 1950")
    assert acceptable_title("Stripping paint from a door") is True


def test_subject_searches_need_every_word_in_the_tags(monkeypatch):
    from core.media.stock_video import _pixabay_clips

    monkeypatch.setenv("PIXABAY_API_KEY", "x")
    rend = {"large": {"url": "u", "width": 1920, "height": 1080}}
    hits = [{"tags": t, "duration": 20, "videos": rend}
            for t in ("gold wash, pan", "ferris wheel, city", "gold medal, sport")]
    monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(
        200, json={"hits": hits}, request=httpx.Request("GET", "https://pixabay.com/")))
    found = _pixabay_clips("gold medal", 5, strict=True)
    assert [h["title"] for h in found] == ["gold medal, sport"]
    assert len(_pixabay_clips("gold medal", 5)) == 3


@pytest.mark.parametrize("tags", ["ai generated, boy", "cube, 3d, puzzle", "hud, eye",
                                  "quiz, puzzle", "cartoon, cat", "clock, green screen"])
def test_clips_that_are_not_filmed_are_refused(monkeypatch, tags):
    from core.media.stock_video import _pixabay_clips

    monkeypatch.setenv("PIXABAY_API_KEY", "x")
    hit = {"tags": tags, "duration": 20,
           "videos": {"large": {"url": "u", "width": 1920, "height": 1080}}}
    monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(
        200, json={"hits": [hit]}, request=httpx.Request("GET", "https://pixabay.com/")))
    assert _pixabay_clips("anything", 5) == []


def test_a_scarce_subject_falls_back_to_its_next_search(monkeypatch, tmp_path):
    from core.media import stock_video

    asked = []

    def clips(query, limit, **kw):
        asked.append((query, kw.get("strict")))
        return [{"url": f"{query}{i}", "length": 20} for i in range(1 if query == "first" else 4)]

    monkeypatch.setattr(stock_video, "_pixabay_clips", clips)
    monkeypatch.setattr(stock_video, "_excerpt", lambda *a: True)
    monkeypatch.setattr(stock_video, "_too_dark", lambda *a: False)
    out = stock_video.fetch_subject_clips({"first|second": 3}, tmp_path)
    assert asked == [("first", True), ("second", True)]
    assert [c["url"] for c in out["first|second"]] == ["first0", "second0", "second1"]
