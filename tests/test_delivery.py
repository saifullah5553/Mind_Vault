"""Expressive narration, the 10-minute limit, credits, chapters and uploaders."""

import json
import shutil
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


def test_visual_plan_groups_short_lines_and_keeps_every_sentence(monkeypatch):
    monkeypatch.setattr(get_settings().video, "speak_chapters", True)
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


def test_description_has_chapters_and_credits_but_no_internal_notes(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings().video, "speak_chapters", True)
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
    credits.add(Path(s.storage_path("images")) / "packtest",
                [{"title": "Sky", "license": "CC0", "source": "Pixabay"}], "image")
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

    pages = {"1": page("CC BY 4.0"), "2": page(""), "3": page("CC BY-NC 4.0"),
             "4": page("CC BY-SA 4.0")}
    reply = httpx.Response(200, json={"query": {"pages": pages}},
                           request=httpx.Request("GET", "https://commons.wikimedia.org/"))
    monkeypatch.setattr(httpx, "get", lambda *a, **k: reply)
    assert [h["license"] for h in stock._commons_search("anything")] == ["CC BY 4.0"]


def test_upload_pack_refuses_a_restricted_credit(tmp_path, monkeypatch):
    from scripts import upload_pack

    bundle = tmp_path / "storage" / "review" / "abc"
    bundle.mkdir(parents=True)
    (bundle / "review.json").write_text("{}", encoding="utf-8")
    (bundle / "metadata.json").write_text("[]", encoding="utf-8")
    images = tmp_path / "storage" / "images"
    monkeypatch.setattr(upload_pack, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(upload_pack, "get_settings", lambda: type("S", (), {
        "storage_path": lambda self, name: tmp_path / "storage" / name,
        "publishing": type("P", (), {"review_dir": "storage/review"})()})())
    # The renderer writes credits under storage/images, not the review bundle.
    with pytest.raises(SystemExit, match="no credits record"):
        upload_pack.build("abc", tmp_path / "out")
    credits.add(images / "abc", [{"title": "Climb talk", "license": "by-nc-nd/3.0",
                                  "source": "Internet Archive"}], "footage")
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
            for t in ("gold wash, pan", "ferris wheel, city", "gold medal, sport",
                      "gold, medallion")]
    monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(
        200, json={"hits": hits}, request=httpx.Request("GET", "https://pixabay.com/")))
    found = _pixabay_clips("gold medal", 5, strict=True)
    assert [h["title"] for h in found] == ["gold medal, sport"]
    assert len(_pixabay_clips("gold medal", 5)) == 4


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


def test_sentence_openers_are_not_people():
    from core.media.themes import known_names, named_subjects

    script = ("In 1971, psychologist Edward Deci gave students a puzzle. Others got nothing. "
              "Deci watched in secret. Afterward, they drew less. Long before, there was Aristotle.")
    known = known_names(script)
    assert named_subjects("Others got nothing.", known) == []
    assert named_subjects("Afterward, they drew less.", known) == []
    assert named_subjects("Deci watched in secret.", known) == ["Deci"]
    assert named_subjects("Aristotle might have agreed.", known) == ["Aristotle"]
    assert named_subjects("Then the money stopped. Give it time.", known) == []
    assert named_subjects("Edward Deci and Richard Ryan agreed.", known) == [
        "Edward Deci", "Richard Ryan"]


def test_ordinary_lines_reach_footage_not_a_portrait_search(monkeypatch, tmp_path):
    from core.registry import get_agent, load_all_agents
    from core.schemas import Scene
    load_all_agents()
    agent = get_agent("video")
    seen = []
    monkeypatch.setattr(agent, "_attach_subject_clips",
                        lambda free, *a: seen.extend(free) or [])
    monkeypatch.setattr("core.media.stock_video.fetch_clip_pool", lambda *a, **k: [])
    lines = ["Psychologist Edward Deci ran it.", "Others got nothing.", "Afterward, they drew less."]
    scenes = [Scene(index=i, narration=t, visual_prompt="x", duration=3)
              for i, t in enumerate(lines)]
    agent._attach_footage(scenes, tmp_path, "topic", "psychology", (640, 360))
    assert [s.narration for s in seen] == lines[1:]


def test_key_green_and_blank_frames_are_unusable():
    from core.media.stock_video import frame_is_unusable

    rng = np.random.default_rng(1)
    scene = rng.integers(0, 255, (2304, 3))
    green = np.tile([58, 176, 11], (2304, 1))
    half_green = np.concatenate([green[:1152], scene[:1152]])
    grass = np.tile([95, 140, 70], (2304, 1)) + rng.integers(-30, 30, (2304, 3))
    assert frame_is_unusable(green)
    assert frame_is_unusable(half_green)
    assert frame_is_unusable(np.tile([200, 200, 200], (2304, 1)))
    assert not frame_is_unusable(scene)
    assert not frame_is_unusable(grass)


def test_pixabay_animations_are_refused(monkeypatch):
    from core.media.stock_video import _pixabay_clips

    monkeypatch.setenv("PIXABAY_API_KEY", "x")
    rend = {"large": {"url": "u", "width": 1920, "height": 1080}}
    hits = [{"tags": "sea, car", "duration": 20, "videos": rend, "type": "animation"},
            {"tags": "sea, boat", "duration": 20, "videos": rend, "type": "film"}]
    asked = {}

    def get(*a, **k):
        asked.update(k["params"])
        return httpx.Response(200, json={"hits": hits},
                              request=httpx.Request("GET", "https://pixabay.com/"))

    monkeypatch.setattr(httpx, "get", get)
    assert [h["title"] for h in _pixabay_clips("sea", 5)] == ["sea, boat"]
    assert asked["video_type"] == "film"


def test_a_minor_tag_is_not_the_subject():
    from core.media.stock_video import _tagged

    assert not _tagged("mud dauber wasps, wasp, insect, hornet, nature, dirt, pottery", "pottery")
    assert _tagged("modeling, clay, pottery, craft", "pottery")
    assert not _tagged("baby, pregnant, woman, belly, motherhood, child", "mother child")
    assert _tagged("friend, people, park", "friends")
    assert _tagged("game, chess, board", "chess")


def test_an_excerpt_survives_an_empty_response(monkeypatch, tmp_path):
    from core.media import stock_video

    monkeypatch.setattr(stock_video, "_RETRY_PAUSE", 0)
    monkeypatch.setattr("core.media.video._ffmpeg_exe", lambda: "ffmpeg")
    dest = tmp_path / "clip.mp4"
    tries = []

    def run(cmd, **kw):
        tries.append(cmd)
        dest.write_bytes(b"x" * (261 if len(tries) < 3 else 30_000))

    monkeypatch.setattr("subprocess.run", run)
    assert stock_video._excerpt("https://example.org/a.mp4", dest, 0.0, 12.0)
    assert len(tries) == 3


def test_a_failed_excerpt_leaves_nothing_behind(monkeypatch, tmp_path):
    from core.media import stock_video

    monkeypatch.setattr(stock_video, "_RETRY_PAUSE", 0)
    monkeypatch.setattr("core.media.video._ffmpeg_exe", lambda: "ffmpeg")
    dest = tmp_path / "clip.mp4"
    monkeypatch.setattr("subprocess.run", lambda cmd, **kw: dest.write_bytes(b"x" * 261))
    assert not stock_video._excerpt("https://example.org/a.mp4", dest, 0.0, 12.0)
    assert not dest.exists()


def test_search_retries_a_rate_limit(monkeypatch):
    from core.media import stock_video

    monkeypatch.setenv("PIXABAY_API_KEY", "x")
    monkeypatch.setattr(stock_video, "_RETRY_PAUSE", 0)
    hit = {"tags": "cat", "duration": 20,
           "videos": {"large": {"url": "u", "width": 1920, "height": 1080}}}
    replies = [429, 503, 200]

    def get(*a, **k):
        code = replies.pop(0)
        return httpx.Response(code, json={"hits": [hit]},
                              request=httpx.Request("GET", "https://pixabay.com/"))

    monkeypatch.setattr(httpx, "get", get)
    assert len(stock_video._pixabay_clips("cat", 1)) == 1
    assert not replies


def test_a_search_failure_never_logs_the_api_key(monkeypatch, caplog):
    from core.media import stock_video

    secret = "SECRET-PIXABAY-KEY"
    monkeypatch.setenv("PIXABAY_API_KEY", secret)
    monkeypatch.setattr(stock_video, "_RETRY_PAUSE", 0)
    url = f"https://pixabay.com/api/videos/?key={secret}"
    monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(
        403, request=httpx.Request("GET", url)))
    monkeypatch.setattr(stock_video.log, "propagate", True)
    with caplog.at_level("DEBUG"):
        assert stock_video._pixabay_clips("cat", 1) == []
    assert "failed" in caplog.text and secret not in caplog.text


@pytest.mark.parametrize("text", [
    "GET https://pixabay.com/api/videos/?key=abc123&q=cat failed",
    "https://graph.facebook.com/v27/me?access_token=abc123",
    "client_secret=abc123 was refused",
])
def test_secrets_in_urls_never_reach_a_log_line(text):
    import logging

    from core.logging_setup import _RedactSecrets

    record = logging.LogRecord("t", logging.ERROR, "f", 1, "failed: %s", (text,), None)
    assert _RedactSecrets().filter(record)
    assert "abc123" not in record.getMessage() and "REDACTED" in record.getMessage()


def test_ordinary_log_lines_are_untouched():
    import logging

    from core.logging_setup import _RedactSecrets

    record = logging.LogRecord("t", logging.INFO, "f", 1, "Placed %d shots", (5,), None)
    _RedactSecrets().filter(record)
    assert record.getMessage() == "Placed 5 shots" and record.args == (5,)


def _live_publish(monkeypatch, run_id, used):
    """Run the publishing agent with dry_run off and a recording uploader."""
    from agents.publishing_agent import agent as publishing
    from core.config import get_settings as settings
    from core.registry import get_agent, load_all_agents
    from core.schemas import PipelineContext, PlatformMetadata, VideoResult

    load_all_agents()
    monkeypatch.setattr(settings().publishing, "dry_run", False)
    sent = []

    class Uploader:
        def is_configured(self):
            return True

        def publish(self, pkg):
            sent.append(pkg)
            return publishing.PublishResult(platform=pkg.platform, status="published")

    monkeypatch.setattr(publishing, "get_publisher", lambda name: Uploader())
    images = Path(settings().storage_path("images")) / run_id
    credits.reset(images)
    if used:
        credits.add(images, used, "footage")
    ctx = PipelineContext(run_id=run_id, category="history", video_format="long",
                          video=VideoResult(video_path="v.mp4", duration=1.0,
                                            resolution=[1920, 1080], engine="test"),
                          metadata=[PlatformMetadata(platform="youtube", title="T", description="D")])
    results = get_agent("publishing").run(ctx)
    shutil.rmtree(images, ignore_errors=True)
    (Path(settings().storage_path("videos")) / f"{run_id}_publish.json").unlink(missing_ok=True)
    return results, sent


def test_real_uploads_stop_on_a_restricted_licence(monkeypatch):
    results, sent = _live_publish(monkeypatch, "gatebad", [
        {"title": "Talk", "license": "by-nc-nd/3.0", "source": "Internet Archive"}])
    assert not sent and results[0].status == "failed" and "Talk" in results[0].note


def test_real_uploads_stop_without_a_credits_record(monkeypatch):
    results, sent = _live_publish(monkeypatch, "gatenone", [])
    assert not sent and "no credits record" in results[0].note


def test_real_uploads_pass_with_clean_credits(monkeypatch):
    results, sent = _live_publish(monkeypatch, "gateok", [
        {"title": "Sky", "license": "CC0", "source": "Pixabay"}])
    assert len(sent) == 1 and results[0].status == "published"


@pytest.mark.parametrize("privacy", ["private", "unlisted"])
def test_instagram_never_posts_while_private(monkeypatch, privacy):
    from core.publishing import instagram
    from core.schemas import PublishPackage

    monkeypatch.setenv("INSTAGRAM_USER_ID", "u")
    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", "t")
    monkeypatch.setenv("INSTAGRAM_VIDEO_URL", "https://example.org/v.mp4")

    def post(*a, **k):
        raise AssertionError("Instagram was called")

    monkeypatch.setattr(instagram.httpx, "post", post)
    pkg = PublishPackage(platform="instagram", video_path="v.mp4", title="T", description="D",
                         privacy=privacy)
    assert instagram.InstagramPublisher().publish(pkg).status == "skipped"


def test_instagram_caption_keeps_the_credits(monkeypatch):
    from core.publishing import instagram
    from core.schemas import PublishPackage

    monkeypatch.setenv("INSTAGRAM_USER_ID", "u")
    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", "t")
    monkeypatch.setenv("INSTAGRAM_VIDEO_URL", "https://example.org/v.mp4")
    sent = []

    def post(url, data, timeout):
        sent.append(data)
        return _Resp(body={"id": "1"})

    monkeypatch.setattr(instagram.httpx, "post", post)
    pkg = PublishPackage(platform="instagram", video_path="v.mp4", title="T",
                         description="Image credits: Ann Lee", hashtags=["#mind"], privacy="public")
    instagram.InstagramPublisher().publish(pkg)
    assert "Image credits: Ann Lee" in sent[0]["caption"] and "#mind" in sent[0]["caption"]


def test_tiktok_caption_keeps_the_credits(monkeypatch, tmp_path):
    from core.publishing import tiktok
    from core.schemas import PublishPackage

    monkeypatch.setenv("TIKTOK_ACCESS_TOKEN", "t")
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x" * 10)
    sent = []

    def post(url, headers, timeout, json=None):
        if json:
            sent.append(json)
        return _Resp(body={"data": {"privacy_level_options": ["SELF_ONLY"],
                                    "upload_url": "https://u", "publish_id": "p"}})

    monkeypatch.setattr(tiktok.httpx, "post", post)
    monkeypatch.setattr(tiktok, "upload_chunks", lambda *a, **k: None)
    pkg = PublishPackage(platform="tiktok", video_path=str(v), title="T",
                         description="Image credits: Ann Lee", hashtags=["#mind"])
    tiktok.TikTokPublisher().publish(pkg)
    assert "Image credits: Ann Lee" in sent[0]["post_info"]["title"]


def test_facebook_uses_the_current_upload_host(monkeypatch, tmp_path):
    from core.publishing import facebook
    from core.schemas import PublishPackage

    for k in ("FACEBOOK_APP_ID", "FACEBOOK_USER_TOKEN", "FACEBOOK_PAGE_ID", "FACEBOOK_PAGE_TOKEN"):
        monkeypatch.setenv(k, "x")
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x" * 10)
    urls = []
    monkeypatch.setattr(facebook, "upload_file", lambda *a, **k: "handle")

    def post(url, timeout, data):
        urls.append(url)
        return _Resp(body={"id": "vid1"})

    monkeypatch.setattr(facebook.httpx, "post", post)
    facebook.FacebookPublisher().publish(PublishPackage(
        platform="facebook", video_path=str(v), title="T", description="D"))
    assert urls[0].startswith("https://graph.facebook.com/")


def test_saving_a_token_replaces_only_its_own_line(tmp_path):
    from scripts.youtube_auth import save_env

    env = tmp_path / ".env"
    env.write_text("# note\nPIXABAY_API_KEY=keep\nYOUTUBE_REFRESH_TOKEN=old\n", encoding="utf-8")
    save_env(env, "YOUTUBE_REFRESH_TOKEN", "new")
    assert env.read_text(encoding="utf-8") == (
        "# note\nPIXABAY_API_KEY=keep\nYOUTUBE_REFRESH_TOKEN=new\n")
    save_env(env, "OTHER", "x")
    assert env.read_text(encoding="utf-8").endswith("YOUTUBE_REFRESH_TOKEN=new\nOTHER=x\n")


def test_youtube_consent_asks_for_a_lasting_token():
    from urllib.parse import parse_qs, urlparse

    from scripts.youtube_auth import SCOPES, consent_url

    q = parse_qs(urlparse(consent_url("id", "http://127.0.0.1:5/", "st", "ch")).query)
    assert q["access_type"] == ["offline"] and q["prompt"] == ["consent"]
    assert q["state"] == ["st"] and q["code_challenge_method"] == ["S256"]
    assert q["scope"][0].split() == SCOPES


@pytest.mark.parametrize("licence", ["CC BY-SA 4.0", "CC BY-SA 3.0", "by-sa/4.0", "CC-BY-SA",
                                     "Creative Commons Attribution-ShareAlike"])
def test_sharealike_stays_out_of_the_videos(licence):
    from core.media.stock import acceptable

    assert credits.is_restricted(licence)
    assert not acceptable({"title": "Fireworks.jpg", "width": 4000, "license": licence}, "psychology")


def test_named_person_with_a_sharealike_photo_is_skipped(monkeypatch, tmp_path):
    from core.media import stock

    monkeypatch.setattr(stock, "_commons_search", lambda q, limit=3, curated=None: [
        {"title": "Edward L Deci.jpg", "width": 3000, "url": "u", "license": "CC BY-SA 4.0"}])
    monkeypatch.setattr(stock, "_download", lambda url, dest: True)
    assert stock.fetch_named("Edward Deci", tmp_path / "a") is None


def test_hashtags_suit_the_platform_and_format():
    from core.registry import get_agent, load_all_agents

    load_all_agents()
    tag = get_agent("seo")._platform_hashtags
    assert "#learnontiktok" not in tag("psychology", "instagram", "short", 8)
    assert "#learnontiktok" in tag("psychology", "tiktok", "short", 5)
    assert "#documentary" not in tag("psychology", "youtube", "short", 3)
    assert tag("psychology", "youtube", "short", 3) == ["#psychology", "#mindvault", "#shorts"]
    assert tag("history", "youtube", "long", 3) == ["#history", "#mindvault", "#documentary"]


def test_script_tags_replace_the_guessed_ones(tmp_path):
    from core.script_file import load

    f = tmp_path / "s.txt"
    f.write_text("TITLE: T\nTAGS: motivation, Edward Deci\n\n[INTRODUCTION]\nHello there.\n",
                 encoding="utf-8")
    assert load(f)[1]["tags"] == "motivation, Edward Deci"


def test_the_closing_line_gets_a_striking_shot():
    from core.media.themes import subject_of

    assert subject_of("Join Mind Vault for more stories about the human mind and history.") \
        .startswith("galaxy")


def test_youtube_uses_a_fresh_token_after_the_upload(monkeypatch, tmp_path):
    from core.publishing import youtube
    from core.schemas import PublishPackage

    v = tmp_path / "v.mp4"
    v.write_bytes(b"x" * 10)
    thumb = tmp_path / "t.png"
    thumb.write_bytes(b"p")
    tokens = iter(["first", "second"])
    monkeypatch.setattr(youtube, "access_token", lambda: next(tokens))
    monkeypatch.setattr(youtube, "_upload_chunks", lambda url, video: {"id": "abc"})
    seen = []

    def post(url, **kw):
        seen.append((url, kw["headers"]["Authorization"]))
        r = _Resp()
        r.headers = {"Location": "https://session"}
        return r

    monkeypatch.setattr(youtube.httpx, "post", post)
    pkg = PublishPackage(platform="youtube", video_path=str(v), title="T", description="D",
                         thumbnail_path=str(thumb))
    assert youtube.YouTubePublisher().publish(pkg).external_id == "abc"
    assert seen[0][1] == "Bearer first" and seen[1][1] == "Bearer second"


def test_loudness_pass_reaches_the_target(tmp_path):
    import re
    import subprocess

    from core.media.video import _ffmpeg_exe, _normalize_loudness

    ff = _ffmpeg_exe()
    if not ff:
        pytest.skip("no ffmpeg")
    src, out = tmp_path / "a.mp4", tmp_path / "b.mp4"
    subprocess.run([ff, "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:r=10:d=12", "-f", "lavfi",
                    "-i", "anoisesrc=d=12:c=pink:a=0.02", "-c:v", "libx264", "-c:a", "aac",
                    "-shortest", str(src)], check=True, capture_output=True)
    assert _normalize_loudness(src, out)
    log = subprocess.run([ff, "-hide_banner", "-nostats", "-i", str(out), "-vn", "-af",
                          "ebur128=framelog=quiet", "-f", "null", "-"],
                         capture_output=True).stderr.decode("utf-8", "replace")
    level = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", log)[-1])
    assert -15.5 < level < -12.5
    assert out.read_bytes().find(b"moov") < out.read_bytes().find(b"mdat")


def test_a_blocked_clip_is_never_used(monkeypatch):
    from core.media import stock_video

    monkeypatch.setenv("PIXABAY_API_KEY", "x")
    hits = [{"id": i, "tags": "classroom, school", "duration": 20,
             "videos": {"large": {"url": f"u{i}", "width": 1920, "height": 1080}}}
            for i in (132048, 7)]
    monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(
        200, json={"hits": hits}, request=httpx.Request("GET", "https://pixabay.com/")))
    assert [c["url"] for c in stock_video._pixabay_clips("classroom", 5)] == ["u7"]


def test_vertical_clips_change_shot_more_often():
    from core.registry import get_agent, load_all_agents
    from core.schemas import Script

    load_all_agents()
    text = " ".join(f"Line {i} is a short one here." for i in range(12))
    script = Script(title="T", hook="H", introduction="", body=text, ending="", cta="", full_text=text,
                    word_count=len(text.split()))
    agent = get_agent("visual")
    short = agent.run({"script": script, "video_format": "short"}).scenes
    long = agent.run({"script": script, "video_format": "long"}).scenes
    assert max(s.duration for s in short) <= 4.0 and len(short) > len(long)


def test_every_video_ends_on_a_disclaimer_card():
    from agents.video_agent.agent import with_disclaimer
    from core.schemas import Scene

    brand = get_settings().brand
    assert brand.disclaimer_screen and brand.disclaimer_description
    scenes = [Scene(index=0, narration="Hello there.", visual_prompt="p", duration=3.0,
                    text_overlay="Hello", clip_path="c.mp4")]
    long = with_disclaimer(scenes, "long", brand)
    short = with_disclaimer(scenes, "short", brand)
    assert len(scenes) == 1 and len(long) == 2
    card = long[-1]
    assert card.animation_kind == "notice" and card.narration == "" and not card.clip_path
    assert card.duration == brand.disclaimer_seconds_long
    assert short[-1].duration == brand.disclaimer_seconds_short


def test_the_disclaimer_card_renders(tmp_path):
    from core.media.animation import render_animated_segment
    from core.media.video import _ffmpeg_exe

    if not _ffmpeg_exe():
        pytest.skip("no ffmpeg")
    out = tmp_path / "n.mp4"
    text = get_settings().brand.disclaimer_screen
    assert render_animated_segment(text, "notice", out, (360, 640), 10, 1.0)
    assert out.stat().st_size > 1000


def test_every_description_carries_the_disclaimer():
    from core.registry import get_agent, load_all_agents
    from core.schemas import PipelineContext

    load_all_agents()
    ctx = PipelineContext(run_id="discl", category="psychology")
    for meta in get_agent("seo").run(ctx):
        assert "Disclaimer:" in meta.description, meta.platform


@pytest.mark.parametrize("title", ["Garofalo and workshop - Coronation of Saint Catherine.jpg",
                                   "Madonna and Child.jpg", "Interior of a mosque.jpg"])
def test_religious_art_stays_out_of_the_mood_pool(title):
    from core.media.stock import acceptable

    assert not acceptable({"title": title, "width": 4000, "license": "CC0"}, "psychology")


def test_advice_lines_are_not_about_football():
    from core.media.themes import subject_of

    assert subject_of("No goal. No score.").startswith("painter")
    assert subject_of("We lose them because someone else set the goal.").startswith("soccer")


def test_one_picture_is_fetched_once(monkeypatch, tmp_path):
    from core.media import stock

    same = {"title": "The Thinker detail.jpg", "width": 4000, "license": "CC0", "source": "Commons"}
    monkeypatch.setattr(stock, "_pexels_photos", lambda q, limit: [])
    monkeypatch.setattr(stock, "_openverse_search", lambda q, limit: [])
    monkeypatch.setattr(stock, "_commons_search", lambda q, limit, curated=None: [
        dict(same, url=f"https://a/{q}.jpg")])
    monkeypatch.setattr(stock, "_download", lambda url, dest: True)
    pool = stock.fetch_themed_pool("t", "psychology", 2, tmp_path,
                                   themes={"a": ("x", ["one"]), "b": ("y", ["two"])})
    assert len(pool) == 1


def test_fallback_stills_do_not_use_up_the_pool(monkeypatch, tmp_path):
    from core.media import images
    from core.schemas import Scene

    pool = [{"path": str(tmp_path / f"p{i}.jpg"), "theme": "mind", "title": f"p{i}",
             "source": "Commons", "license": "CC0"} for i in range(3)]
    monkeypatch.setattr(get_settings().images, "provider", "stock")
    monkeypatch.setattr("core.media.stock.fetch_themed_pool", lambda *a, **k: pool)
    monkeypatch.setattr(images, "_named_image", lambda *a, **k: None)
    picked = []

    def fake_still(path, scene, out, *a, **k):
        picked.append((scene.index, Path(path).name))
        return True

    monkeypatch.setattr(images, "_cinematic_from_photo", fake_still)
    scenes = [Scene(index=i, narration="An idea about the mind.", visual_prompt="p", duration=3,
                    clip_path=("c.mp4" if i % 2 else None)) for i in range(6)]
    images.generate_images(scenes, tmp_path, topic="t", category="psychology")
    shown = [name for i, name in picked if i % 2 == 0]
    assert len(shown) == 3 and len(set(shown)) == 3


@pytest.mark.parametrize("title,ok", [
    ("Sarah Chepchirchir - Paris Half Marathon - 5245.jpg", False),
    ("David Bizet - Marathon de Paris 2014.jpg", False),
    ("Fireworks over a bridge.jpg", True),
    ("Crafting pot, pottery art.jpg", True),
    ("Free fog forest image.jpg", True),
    ("Aristotle with a Bust of Homer MET DP319026.jpg", True),
])
def test_named_strangers_stay_out_of_the_mood_pool(title, ok):
    from core.media.stock import acceptable

    assert acceptable({"title": title, "width": 4000, "license": "CC0"}, "psychology") is ok


def test_thumbnail_uses_only_photos_the_video_shows(tmp_path, monkeypatch):
    from PIL import Image

    from core.registry import get_agent, load_all_agents

    load_all_agents()
    agent = get_agent("thumbnail")
    folder = tmp_path / "images" / "thumbrun"
    folder.mkdir(parents=True)
    Image.new("RGB", (64, 36), (20, 20, 200)).save(folder / "scene_000.jpg")   # vivid, unshown
    Image.new("RGB", (64, 36), (120, 110, 100)).save(folder / "scene_001.jpg")  # dull, shown
    monkeypatch.setattr(type(agent.settings), "storage_path", lambda self, name: str(tmp_path / name))
    picked = agent._best_photos("thumbrun", 3, [str(folder / "scene_001.jpg")])
    assert [p.name for p in picked] == ["scene_001.jpg"]


def test_chapters_are_not_announced_by_default():
    from core.media.spoken import spoken_text

    script = "[INTRODUCTION]\nHello there.\n\n[CHAPTER: Origins]\nIt began in Rome.\n\n[CTA]\nJoin us."
    assert "Chapter" not in spoken_text(script)
    assert "It began in Rome." in spoken_text(script)
    assert "Chapter one: Origins." in spoken_text(script, speak_chapters=True)


def test_country_histories_are_in_the_topic_pool():
    from core.taxonomy import subcategories

    subs = subcategories("history")
    assert "Japan" in subs and "ancient civilizations" in subs


def test_one_documentary_every_day():
    from datetime import date, timedelta

    from scripts.autopilot import plan_jobs

    s = get_settings()
    start = date(2026, 11, 9)
    for i in range(7):
        assert "long" in plan_jobs(start + timedelta(days=i), s)


def test_release_slots_follow_the_audience_clock():
    from datetime import datetime, timezone

    from scripts.go_live import next_release_slot

    pub = get_settings().publishing
    # Mon 9 Nov 2026, 03:30 Dubai = Sun 8 Nov 18:30 New York: Sunday's 10:00 has passed.
    now = datetime(2026, 11, 8, 23, 30, tzinfo=timezone.utc)
    slot = next_release_slot(now, pub, [])
    assert slot == datetime(2026, 11, 9, 19, 0, tzinfo=timezone.utc)     # Mon 14:00 New York
    # A taken slot moves the next video to the following day.
    nxt = next_release_slot(now, pub, [slot.isoformat()])
    assert nxt == datetime(2026, 11, 10, 19, 0, tzinfo=timezone.utc)
    # Saturday uses the weekend time.
    sat = next_release_slot(datetime(2026, 11, 13, 20, 0, tzinfo=timezone.utc), pub, [])
    assert sat == datetime(2026, 11, 14, 15, 0, tzinfo=timezone.utc)     # Sat 10:00 New York


def test_a_slot_too_close_to_now_is_skipped():
    from datetime import datetime, timezone

    from scripts.go_live import next_release_slot

    pub = get_settings().publishing
    now = datetime(2026, 11, 9, 18, 30, tzinfo=timezone.utc)              # 13:30 New York
    assert next_release_slot(now, pub, []) == datetime(2026, 11, 10, 19, 0, tzinfo=timezone.utc)


def _written_script(tmp_path, facts=6, topic=True):
    script = tmp_path / "japan.txt"
    script.write_text(
        ("TOPIC: the history of Japan\n" if topic else "")
        + "TITLE: How Japan Opened to the World\nTAGS: japan, meiji\n\n"
        "[INTRODUCTION]\nIn 1853, four black ships sailed into Edo Bay.\n\n"
        "[CHAPTER: Change]\nWithin fifteen years, the shogunate was gone.\n\n"
        "[CTA]\nJoin Mind Vault for more stories about the human mind and history.\n",
        encoding="utf-8")
    (tmp_path / "japan.sources.txt").write_text("\n".join(
        f"Fact number {i} about Japan | https://www.britannica.com/place/Japan/{i}"
        for i in range(facts)), encoding="utf-8")
    return script


def test_a_written_script_starts_a_run_without_the_local_model(tmp_path):
    from core.orchestrator import Orchestrator
    from core.registry import load_all_agents

    load_all_agents()
    ctx = Orchestrator.context_from_script(str(_written_script(tmp_path)), "history")
    assert ctx.topic.topic == "the history of Japan" and ctx.topic.angle == "How Japan Opened to the World"
    assert len(ctx.fact_verdicts) == 6 and all(v.status == "approved" for v in ctx.fact_verdicts)
    assert ctx.extra["approved_facts"][0]["url"].startswith("https://www.britannica.com/")
    assert ctx.selected_hook.text.startswith("In 1853") and ctx.selected_hook.total > 0
    assert {"research", "fact", "hook", "script"} <= set(ctx.completed_stages)
    assert "visual" not in ctx.completed_stages


def test_a_written_script_needs_a_topic_and_sources(tmp_path):
    from core.errors import Mind_VaultError
    from core.orchestrator import Orchestrator
    from core.registry import load_all_agents

    load_all_agents()
    with pytest.raises(Mind_VaultError, match="TOPIC"):
        Orchestrator.context_from_script(str(_written_script(tmp_path, topic=False)), "history")
    with pytest.raises(Mind_VaultError, match="at least 5"):
        Orchestrator.context_from_script(str(_written_script(tmp_path, facts=3)), "history")


def _report_for(monkeypatch, tmp_path, locked, duration=500.0):
    from core.registry import get_agent, load_all_agents
    from core.schemas import FactVerdict, Hook, PipelineContext, Script, VideoResult, VoiceResult

    load_all_agents()
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    text = "In 1853 four ships came. " * 40
    ctx = PipelineContext(run_id="qa_locked", category="history", video_format="long")
    ctx.script = Script(title="T", hook="In 1853 four ships came.", introduction="", body=text,
                        ending="", cta="", full_text=text, word_count=200)
    ctx.selected_hook = Hook(text="In 1853 four ships came.", total=60.0)
    ctx.fact_verdicts = [FactVerdict(claim=f"c{i}", confidence=95, status="approved") for i in range(6)]
    ctx.voice = VoiceResult(audio_path=str(audio), duration=duration, provider="t", voice="t")
    ctx.video = VideoResult(video_path=str(video), duration=duration, resolution=[1, 1], engine="t")
    if locked:
        ctx.extra["title_locked"] = True
    agent = get_agent("quality")
    monkeypatch.setattr(agent, "_originality", lambda payload: 99.0)
    return agent.run(ctx)


def test_a_written_script_is_not_blocked_by_the_keyword_hook_score(monkeypatch, tmp_path):
    report = _report_for(monkeypatch, tmp_path, locked=True)
    assert report.passed
    assert any(r.startswith("advisory: hook_score") for r in report.reasons)
    assert not _report_for(monkeypatch, tmp_path, locked=False).passed


def test_a_written_script_over_the_length_limit_still_fails(monkeypatch, tmp_path):
    report = _report_for(monkeypatch, tmp_path, locked=True, duration=700.0)
    assert not report.passed and any("limit" in r for r in report.reasons)


def test_history_lines_get_no_psychology_b_roll(monkeypatch, tmp_path):
    """The Iceland film showed a dog, a guitarist and sneakers over history lines."""
    from core.registry import get_agent, load_all_agents
    from core.schemas import Scene
    load_all_agents()
    agent = get_agent("video")
    asked = []
    monkeypatch.setattr(agent, "_attach_subject_clips",
                        lambda scenes, *a, **k: asked.append(1) or scenes)
    monkeypatch.setattr("core.media.stock_video.fetch_clip_pool", lambda *a, **k: [])
    scenes = [Scene(index=0, narration="It lived in the books they were reading.",
                    visual_prompt="x", duration=3)]
    agent._attach_footage(scenes, tmp_path, "Thingvellir", "history", (640, 360))
    assert not asked
    agent._attach_footage(scenes, tmp_path, "motivation", "psychology", (640, 360))
    assert asked


@pytest.mark.parametrize("title", [
    "Riksdagshuset Parliament House Kungliga Operan Stockholm 2016 02.jpg",
    "20180313 Bjorn Thor Arnarson Copenhagen University 0007 (25915953827).jpg",
    "Crown Prince Haakon of Norway 2010-09-06 001.jpg",
    "Íslendingabók - AM 113 a fol. - 001.jpg",
    "Haakon in 2025 (cropped).jpg",
    "King Haakon VII of Norway boarding MS Venus.jpg",
    "Íslendingabók - AM 113 b fol. - 002.jpg",
    "Sambandslaganefndin in front of Alþingishúsið in Reykjavík.jpg",
])
def test_wrong_iceland_pictures_are_blocked(title):
    from core.media.stock import acceptable
    assert not acceptable({"title": title, "license": "CC0", "width": 3000}, "history")


@pytest.mark.parametrize("title", [
    "80th Shimoda Black Ship Festival (5374683).jpg",
    "CUNY School of Medicine - Townsend Harris Hall (48170427627).jpg",
    "Dr. Francis Townsend & Rep. A.J. Elliott LCCN2016875233.jpg",
    "E.D Morel, ca. 1900-1915 (IMP-CSCNWW33-OS10-23).jpg",
    "DuchesneDeBellecourt1860.JPG",
    "02023 Single-edged sword from the Przeworsk Culture found in Masów.jpg",
    "Site of Ichi-tamon Gate historical marker - 2-2 Osakajo, Chuo Ward, Osaka, 540-0002, Japan.jpg",
    "US Navy 100514-N-0051B-209 Rear Adm. Richard Wren.jpg",
    "Dr. Townsend & Sen. Lodge LCCN2016873559.jpg",
    "Francis Townsend, seated at desk, reading papers hec.27729.jpg",
    "AmputationOsaka.jpg",
    "Bijin Oiran.jpg",
    "Otani Hiroji as Kurofune Chiemon",
    "French and American treaty from 1922 LCCN2016863071.jpg",
    "February 2024, buildings in Yokohama 10.jpg",
    "Izukyu Resort21 Kurofune Kawana Futo.jpg",
    "Harris Hall 1589 Amst Av jeh.jpg",
    "Air shot, Cape May (N.J.) Coast Guard Station Airport by Harris & Ewing, photographer",
    "Rivers and bridges in Yokohama 16.jpg",
    "CFAY, NAVSUP FLC Yokosuka Clean Yokohama Foreign General Cemetery (9051043).jpg",
])
def test_wrong_japan_pictures_are_blocked(title):
    from core.media.stock import acceptable
    assert not acceptable({"title": title, "license": "CC0", "width": 3000}, "history")


@pytest.mark.parametrize("title", [
    "Althaea officinalis, 2020-10-04, Carnegie, 01.jpg",
    "Bing Crosby looking at his newborn son.jpg",
    "Animal Crackers (1928) 02.jpg",
    "1940 Census Enumeration District Maps - Connecticut - Windham County - Brooklyn - ED 8-3 - NARA - 5829561.jpg",
    "Air assault slingload test.jpg",
    "President Lyndon B. Johnson at the dedication of University of California Irvine (13768686434).jpg",
    "Ary Scheffer - Les ombres de Francesca da Rimini et de Paolo Malatesta.jpg",
    "1934 Erlöserkirche Am Schüttel img01.jpg",
    "Memorial Church at Stanford University.jpg",
    "Pro-Palestine Vandalism of Stanford Quad (53772388133).jpg",
    "USMC-12733.jpg",
    "2021 Chevrolet Spark LS in Toasted Marshmallow, front left, 07-13-2022.jpg",
    "Hoover Dam Spillway Tower.jpg",
    "University of Southern California assistant football coach E. A. Irvine, USC campus, Los Angeles, 1915.jpg",
    "Helmand's largest hospital introduces new MRI capabilities 111015-M-DF801-032.jpg",
])
def test_wrong_marshmallow_pictures_are_blocked(title):
    from core.media.stock import acceptable
    assert not acceptable({"title": title, "license": "CC0", "width": 3000}, "history")


def test_marshmallow_pictures_still_allowed():
    from core.media.stock import acceptable
    for title in ("Crayola crayons.jpg", "Low Library2.jpg", "Stanford University Aerial View.jpg",
                  "Pink Marshmallow squashed into a Strange Shape.jpg",
                  "Tower at Stanford.jpg", "Reading room in Rush Rhees library at the University of Rochester.jpg"):
        assert acceptable({"title": title, "license": "CC0", "width": 3000}, "history"), title


def test_japan_pictures_still_allowed():
    from core.media.stock import acceptable
    for title in ("Iwakura mission.jpg", "Townsend Harris portrait.jpg", "Commodore Matthew Calbraith Perry.jpg",
                  "Iron window door on brick wall of warehouse, Tomioka Silk Mill.jpg"):
        assert acceptable({"title": title, "license": "CC0", "width": 3000}, "history")


def test_peoples_are_not_captioned(tmp_path):
    from PIL import Image

    from core.media.images import _direct
    from core.media import maps
    from core.schemas import Scene
    if not maps.ensure_data():
        pytest.skip("map data not available")
    photo = tmp_path / "p.jpg"
    Image.new("RGB", (100, 100)).save(photo)
    state = {"showcases": [], "labelled": set(), "labels": []}
    s = Scene(index=0, narration="It said that Americans accused of crimes would be tried.",
              visual_prompt="", duration=3)
    _direct(s, {"title": "Alexander Gardner (American, born Scotland) Japanese Ambassadors",
                "path": str(photo)}, tmp_path, state)
    assert s.label == ""


@pytest.mark.parametrize("title", [
    "Self Described and Self Defined (1965) - Joseph Kosuth (1948) (24010621475).jpg",
    "2024-12-20 13-26-11 CZ PRG Tutankhamun exhib JHe N9.jpg",
    "Battle of the Pyramids 1798.jpg",
    "Destruction of the French Fleet at Toulon 18th December 1793.jpg",
    "Mediterranean Cave in Gibraltar 1902 Illustrated London News photo.jpg",
    "Caslon 1841 specimen Eight-line Pica antique (slab-serif) shaded typeface.jpg",
    "2017-02 Sir Thomas Lawrence - Portrait of a young man, said to be John Millington, Esq..jpg",
    "Ancient Greek Loutrophoros.jpg",
    "Basic cartouche on a Sarmatia map by Mercator.jpg",
    "Dagestani man and woman.jpg",
    "Botticelli - Portrait of a Young Man Holding a Roundel.jpg",
    "Laying a corner stone for a new club for IDF soldiers in Ashdod (FL63120169).jpg",
    'Caslon shaded slab serif, 1841 "Gin".jpg',
    "De oprichting van de obelisk op het St. Pietersplein, RP-P-OB-207.655.jpg",
])
def test_wrong_rosetta_pictures_are_blocked(title):
    from core.media.stock import acceptable
    assert not acceptable({"title": title, "license": "CC0", "width": 3000}, "history")


def test_rosetta_pictures_still_allowed():
    from core.media.stock import acceptable
    for title in ("June 2008 Rosetta stone.jpg", "Portrait of Thomas Young.jpg",
                  "Jean-François Champollion, by Léon Cogniet.jpg", "Hiéroglyphes - Temple de Karnak.jpg",
                  "The Rosetta Stone (Left Side) - British Museum.jpg", "Egyptienne frigate.jpg"):
        assert acceptable({"title": title, "license": "CC0", "width": 3000}, "history"), title


def test_rosetta_clips_blocked():
    from core.media.stock_video import _BLOCKED_IDS
    assert {14476, 214940, 80817, 200023, 45132} <= _BLOCKED_IDS


@pytest.mark.parametrize("title", [
    "2017-01-19 Vladimir Putin and Dmitry Medvedev with Mintimer Shaimiyev on the eve of his 80th birthday, 01.jpg",
    "Gen. Tod D. Wolters EUCOM.jpg",
    "Koki Ozora.jpg",
    "Revolver, percussion (AM 559402-1).jpg",
    "Hans Thoma - Daniel in der Löwengrube (1886).jpg",
    "19170704 Riot on Nevsky prosp Petrograd (original).jpg",
    "I.P. Pavlov with three colleagues operating on a dog in the Wellcome L0022540.jpg",
    "Elkanah Watson (NYPL b13476046-EM11399).jpg",
    "Kostel Pavlov1 (Žďár).JPG",
])
def test_wrong_pavlov_pictures_are_blocked(title):
    from core.media.stock import acceptable
    assert not acceptable({"title": title, "license": "CC0", "width": 3000}, "history")


def test_pavlov_pictures_still_allowed():
    from core.media.stock import acceptable
    for title in ("Ivan-Pavlov06.jpg", "Dogs with their keepers at the Physiology Department Wellcome L0022519.jpg",
                  "Metronome (2555843095).jpg", "House where I. P. Pavlov.jpg"):
        assert acceptable({"title": title, "license": "CC0", "width": 3000}, "history"), title
