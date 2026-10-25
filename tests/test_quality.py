"""Defects found by reviewing the first real 12-minute documentary."""

from core.media.spoken import headline, spoken_text


def test_markers_are_not_read_aloud_and_chapters_are_spoken():
    script = ("[INTRODUCTION]\nThe hook line.\n\n[CHAPTER: Origins]\nIt began here.\n\n"
              "[CHAPTER: The Turning Point]\nThen it changed.\n\n[CONCLUSION]\nSo.\n\n"
              "[CTA]\nFollow for more.")
    s = spoken_text(script)
    assert "[" not in s and "INTRODUCTION" not in s and "CTA" not in s
    assert "Chapter one: Origins." in s and "Chapter two: The Turning Point." in s
    # The chapter heading is its own sentence, not glued to the next one.
    assert "Origins. " not in s.replace("\n", " ").split("It began")[0][-3:]


def test_on_screen_text_is_a_phrase_not_a_cut_sentence():
    assert "…" not in headline("And as we continue our journey into the world of "
                               "motivation, we find that habits matter more than goals.")
    assert headline('Thorndike described "the law of effect" in 1911.') == "The law of effect"
    assert headline("Chapter two: The Turning Point.") == "Chapter two: The Turning Point"
    words = headline("This notion posits that a person's character is shaped by "
                     "experience over many years.").split()
    assert len(words) <= 8 and words[-1].lower() not in {"a", "the", "of", "that", "is"}


def test_image_filter_blocks_unsafe_and_diagrams():
    from core.media.stock import acceptable
    blocked = ["Replication of the MFM of sexual offending.png",
               "Sternberg's Triangle of Love.jpg", "Motivation table.jpg"]
    assert not any(acceptable({"title": t}, "psychology") for t in blocked)
    assert not acceptable({"title": "Unabomb06"}, "psychology")
    assert acceptable({"title": "Essex coastline 1890.jpg"}, "history")
    assert acceptable({"title": "Battle of Verdun 1916.jpg"}, "history")
    assert not acceptable({"title": "Street.jpg", "width": 800}, "history")   # not HD


def test_scene_durations_add_up_to_the_narration():
    from core.media.video import _frame_exact
    from core.schemas import Scene
    fps = 30
    scenes = [Scene(index=i, narration="x", visual_prompt="x", duration=7.7517)
              for i in range(93)]
    durs = _frame_exact(scenes, fps)
    total_frames = sum(round(d * fps) for d in durs)
    assert total_frames == round(93 * 7.7517 * fps)       # nothing lost to rounding


def test_text_never_leaves_its_box():
    from PIL import Image, ImageDraw

    from core.media.animation import _fit_text, _font
    d = ImageDraw.Draw(Image.new("RGB", (2560, 1440)))
    long = "Thorndike's concept of learned motivation posits that motivation " * 4
    f, wrapped = _fit_text(d, long, lambda s: _font(s), 1900, 180, max_h=500)
    box = d.multiline_textbbox((0, 0), wrapped, font=f, spacing=10)
    assert box[2] - box[0] <= 1900 and box[3] - box[1] <= 500


def test_every_animation_kind_renders_inside_the_frame(tmp_path):
    """Draw each kind at full progress; no ink may touch the frame's edge."""
    import numpy as np
    from core.media.animation import _RENDERERS, Style, _background
    res = (2560, 1440)
    text = ("Our motivations can either empower or hinder us; habits shape what we "
            "repeat. 42% of people quit within a year. Because rewards fade, goals drift")
    for kind, draw in _RENDERERS.items():
        img = _background(res, Style())
        before = np.asarray(img).copy()
        draw(img, text, Style(), res, 1.0)
        diff = np.abs(np.asarray(img).astype(int) - before.astype(int)).sum(axis=2) > 40
        edge = np.concatenate([diff[:, :8].ravel(), diff[:, -8:].ravel(),
                               diff[:8, :].ravel(), diff[-8:, :].ravel()])
        assert not edge.any(), f"{kind} draws off the frame"


def test_ceo_report_states_only_measured_facts():
    from core.registry import get_agent, load_all_agents
    load_all_agents()
    report = get_agent("ceo").execute({}).output
    assert report.summary.startswith("No published videos yet")
    assert "$" not in report.summary and "revenue" not in report.summary.lower()


def test_chapter_headings_get_title_cards():
    from core.registry import get_agent, load_all_agents
    from core.schemas import Scene
    load_all_agents()
    agent = get_agent("video")
    scenes = [Scene(index=i, narration=t, visual_prompt="x", duration=3.0, image_path="p.jpg")
              for i, t in enumerate(["Intro line here.", "Plain sentence about habits.",
                                     "Chapter three: The Hidden Pattern.", "Another plain one."])]
    agent.config["animation_max_ratio"] = 0.0
    agent._mark_animated(scenes)
    assert scenes[2].animation_kind == "title"


# ── eye-catching imagery ────────────────────────────────────────────────────
def test_scenes_get_imagery_by_mood_without_repeats():
    from core.media.themes import pick, theme_of
    assert theme_of("They kept striving toward the summit of their goals") == "ambition"
    assert theme_of("Doubt and fear made them quit") == "struggle"
    assert theme_of("A plain sentence") == "default"
    pool = [{"path": f"a{i}", "theme": "ambition"} for i in range(2)] + \
           [{"path": f"d{i}", "theme": "default"} for i in range(3)]
    used: dict = {}
    picks = [pick("achieve your goals", pool, used)["path"] for _ in range(4)]
    assert picks[:2] == ["a0", "a1"]               # on-theme first
    assert len(set(picks)) == 4                    # then unused pictures, no repeats


def test_shots_are_spread_across_the_film():
    from core.media.stock_video import _seconds, shot_offsets
    assert _seconds("10:12") == 612 and _seconds("612.5") == 612.5 and _seconds(None) == 0
    offs = shot_offsets(600, 4, 9)
    assert len(set(offs)) == 4 and offs[0] >= 600 * 0.08 and offs[-1] + 9 <= 600 * 0.88
    assert len(set(shot_offsets(0, 3, 9))) == 3    # unknown length still distinct


def test_modern_uploads_are_not_archival_footage(monkeypatch):
    from core.media import stock_video as sv

    def meta(title, year, coll="prelinger"):
        return {"metadata": {"title": title, "year": year, "collection": [coll]},
                "files": [{"name": "a.mp4", "height": "480", "width": "640"}]}

    class R:
        def __init__(self, d): self.d = d
        def raise_for_status(self): pass
        def json(self): return self.d

    for m, ok in [(meta("Motivation and Reward in Learning", "1948"), True),
                  (meta("Roguelike Celebration 2023", ""), False),
                  (meta("Some Film", "2011"), False),
                  (meta("Old Film", "1950", coll="opensource_movies"), False)]:
        monkeypatch.setattr("httpx.get", lambda *a, _m=m, **k: R(_m))
        assert (sv._ia_file("x") is not None) == ok, m["metadata"]["title"]


def test_each_footage_shot_is_used_once(monkeypatch, tmp_path):
    from core.registry import get_agent, load_all_agents
    from core.schemas import Scene
    load_all_agents()
    agent = get_agent("video")
    shots = [{"path": f"shot{i}.mp4", "url": f"u{i}", "title": "t", "source": "IA",
              "license": "pd"} for i in range(3)]
    monkeypatch.setattr("core.media.stock_video.fetch_clip_pool", lambda *a, **k: shots)
    scenes = [Scene(index=i, narration="x", visual_prompt="x", duration=3) for i in range(9)]
    scenes[0].animation_kind = "title"
    agent._attach_footage(scenes, tmp_path, "topic", "history", (640, 360), burn=False)
    used = [s.clip_path for s in scenes if s.clip_path]
    assert sorted(used) == ["shot0.mp4", "shot1.mp4", "shot2.mp4"]   # once each
    assert scenes[0].clip_path is None                                # cards stay cards
    assert all(s.overlay_png is None for s in scenes)                 # long-form: clean
