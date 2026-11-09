"""Parallel scene rendering: same output as serial, settings reach the workers."""

import pytest

from core.config import get_settings
from core.media import video
from core.schemas import Scene


def _jobs(tmp_path):
    ffmpeg = video._ffmpeg_exe()
    if not ffmpeg:
        pytest.skip("ffmpeg not available")
    tmp_path.mkdir(parents=True, exist_ok=True)
    kinds = ["title", "stat", "quote", "bullets"]
    return [(i, Scene(index=i, narration=f"Beat {i}: 42% of people", visual_prompt="x",
                      duration=0.8, text_overlay=f"Beat {i}", animation_kind=k),
             tmp_path / f"p{i:04d}.mp4", [320, 180], 10, "Mind_Vault", ffmpeg)
            for i, k in enumerate(kinds)]


def test_parallel_render_matches_serial_in_order(tmp_path):
    s = get_settings()
    s.video.render_workers = 1
    serial = video._render_parts(_jobs(tmp_path / "serial"))
    s.video.render_workers = 3
    jobs = _jobs(tmp_path / "parallel")
    parallel = video._render_parts(jobs)
    assert parallel == serial == ["anim"] * 4
    assert all(j[2].stat().st_size > 0 for j in jobs)


def test_worker_receives_parent_settings():
    s = get_settings()
    dump = s.model_dump()
    dump["video"]["crf"] = 31
    dump["brand"]["name"] = "Worker Copy"
    video._init_worker(dump)          # what each worker runs on start-up
    assert get_settings().video.crf == 31
    assert get_settings().brand.name == "Worker Copy"


def test_worker_count_respects_config_and_job_count():
    s = get_settings()
    s.video.render_workers = 4
    assert video._render_workers(2) == 2
    assert video._render_workers(10) == 4
    s.video.render_workers = 0
    assert video._render_workers(1) == 1


def test_ken_burns_segment_is_exactly_its_scene_length(tmp_path):
    """The old zoompan filter turned a 7 s scene into a ~10 minute clip."""
    import subprocess

    from PIL import Image
    ffmpeg = video._ffmpeg_exe()
    if not ffmpeg:
        pytest.skip("ffmpeg not available")
    img = tmp_path / "still.jpg"
    Image.new("RGB", (800, 500), (40, 90, 160)).save(img)
    for mode in range(4):
        s = Scene(index=mode, narration="x", visual_prompt="x", duration=1.2,
                  image_path=str(img))
        out = tmp_path / f"kb{mode}.mp4"
        assert video._kenburns_segment(ffmpeg, s, mode, 1.2, (320, 180), 10, out)
        raw = subprocess.run([ffmpeg, "-v", "error", "-i", str(out), "-f", "rawvideo",
                              "-pix_fmt", "gray", "-"], capture_output=True).stdout
        frames = len(raw) // (320 * 180)
        assert frames == 12, (mode, frames)


def test_topic_parts_tie_picture_searches_to_their_lines():
    from core.media.stock import part_per_line, topic_parts
    topic = "Watersnood 1953 @ flood|storm; Kinderdijk @ windmill; Maeslantkering @ Rotterdam"
    assert [q for q, _ in topic_parts(topic)] == ["Watersnood 1953", "Kinderdijk",
                                                  "Maeslantkering"]
    lines = ["The storm came at night.", "Inside the dikes, they pumped it dry.",
             "The pumps were windmills.", "They still stand.", "Rotterdam is a port.",
             "Ships pass through it."]
    assert part_per_line(lines, topic) == [0, 0, 1, 1, 2, 2]
    # A plain topic is one search, and every line belongs to it.
    assert topic_parts("the history of Japan") == [("the history of Japan", None)]
    assert part_per_line(["a", "b"], "the history of Japan") == [0, 0]


def test_history_pictures_exclude_religious_and_hell_art():
    from core.media.stock import acceptable
    ok = {"license": "CC0", "width": 3000}
    assert not acceptable(dict(ok, title="Bosch - The Hell and the Flood - interior"), "history")
    assert not acceptable(dict(ok, title="The Flood MET DP169129"), "history")
    assert not acceptable(dict(ok, title="To the Genius of Franklin by Fragonard"), "history")
    assert acceptable(dict(ok, title="Dijkdoorbraak bij Zierikzee, NG-2009-30"), "history")
    # A history pool may show a named place or person (Lely on his dam).
    assert acceptable(dict(ok, title="Cornelis Lely - Afsluitdijk (32896245132)"), "history")


def test_loudness_pass_ends_with_a_limiter():
    from core.media.video import _loudness_filter
    m = {"input_i": "-20", "input_tp": "-3", "input_lra": "7", "input_thresh": "-30",
         "target_offset": "0.2"}
    f = _loudness_filter(m)
    assert f.startswith("loudnorm=") and "measured_I=-20" in f
    assert f.endswith("alimiter=limit=0.708:level=disabled")


def test_rerender_script_file_updates_the_topic(tmp_path):
    from core.orchestrator import Orchestrator
    from core.schemas import ScoredTopic

    script = tmp_path / "s.txt"
    script.write_text("TOPIC: Kinderdijk @ windmill; Maeslantkering @ Rotterdam\n"
                      "TITLE: A Title\n\n[INTRODUCTION]\nThe pumps were windmills.\n"
                      "\n[CTA]\nJoin Mind Vault for more stories about the human mind and history.\n",
                      encoding="utf-8")

    class Ctx:
        topic = ScoredTopic(topic="old topic", category="history")
        extra: dict = {}
        script = None

    class Stub:
        def _update_content(self, ctx, **kw):
            pass

    ctx = Ctx()
    Orchestrator._use_script(Stub(), ctx, str(script))
    assert ctx.topic.topic.startswith("Kinderdijk @ windmill")


def test_a_topic_part_can_name_several_searches(monkeypatch, tmp_path):
    from core.media import stock
    asked = []

    def provider(q, limit):
        asked.append(q)
        return [{"url": f"https://x/{q}/{i}.jpg", "title": f"{q} photo {'abc'[i]}", "license": "CC0",
                 "width": 3000, "source": "test"} for i in range(3)]

    monkeypatch.setattr(stock, "_commons_search", provider)
    monkeypatch.setattr(stock, "_openverse_search", lambda q, limit: [])
    monkeypatch.setattr(stock, "_download", lambda url, dest: True)
    pool = stock.fetch_pool("Deltawerken + Haringvlietdam @ Delta; Kinderdijk @ windmill",
                            12, tmp_path, "history")
    assert "Deltawerken" in asked and "Haringvlietdam" in asked
    assert sum(1 for h in pool if h["part"] == 0) == 6     # both searches fill part 0
    assert not stock.acceptable({"title": "Afsluitdijk - wind turbines", "license": "CC0",
                                 "width": 3000}, "history")


def test_the_pool_keeps_one_copy_of_the_same_picture(monkeypatch, tmp_path):
    from PIL import Image, ImageDraw

    from core.media import stock

    def picture(dest, shift):
        im = Image.new("RGB", (400, 300), (200, 200, 200))
        d = ImageDraw.Draw(im)
        d.rectangle((50 + shift, 40, 220 + shift, 260), fill=(20, 20, 20))
        d.ellipse((260, 60, 380, 180), fill=(90, 90, 90))
        im.save(dest, "JPEG")

    files = {"a": 0, "b": 2, "c": None}           # b is a second print of a; c differs

    def download(url, dest):
        key = url.rsplit("/", 1)[1]
        if files[key] is None:
            im = Image.new("RGB", (400, 300), (30, 30, 30))
            ImageDraw.Draw(im).rectangle((200, 0, 400, 150), fill=(250, 250, 250))
            im.save(dest, "JPEG")
        else:
            picture(dest, files[key])
        return True

    hits = [{"url": f"https://x/{k}", "title": f"print {k}", "license": "CC0", "width": 3000,
             "source": "t"} for k in files]
    monkeypatch.setattr(stock, "_commons_search", lambda q, limit: hits)
    monkeypatch.setattr(stock, "_openverse_search", lambda q, limit: [])
    monkeypatch.setattr(stock, "_download", download)
    pool = stock.fetch_pool("Dijkdoorbraak", 3, tmp_path, "history")
    assert [h["url"][-1] for h in pool] == ["a", "c"]
    assert not stock.acceptable({"title": "North Sea Edward Wadsworth 1928", "license": "CC0",
                                 "width": 3000}, "history")


def test_named_pictures_get_the_same_subject_checks(monkeypatch, tmp_path):
    from core.media import stock
    hits = [{"url": "https://x/a.jpg", "title": "North Sea Edward Wadsworth 1928", "license": "PD",
             "width": 3000, "source": "t"},
            {"url": "https://x/b.jpg", "title": "North Sea coast at Westkapelle in 1953",
             "license": "PD", "width": 3000, "source": "t"}]
    monkeypatch.setattr(stock, "_commons_search", lambda q, limit: hits)
    monkeypatch.setattr(stock, "_download", lambda url, dest: True)
    got = stock.fetch_named("North Sea", tmp_path / "n.jpg", "history")
    assert got and got["url"].endswith("b.jpg")


def test_blocked_titles_match_as_commons_returns_them():
    from core.media.stock import acceptable
    for title in ("Nederland 1916 rus.jpg", "File:Nederland 1916 rus.jpg",
                  "North Sea Edward Wadsworth 1928.jpg"):
        assert not acceptable({"title": title, "license": "PD", "width": 3000}, "history")
