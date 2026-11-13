"""The camera director (core/media/camera.py) and sound design (core/media/sfx.py)."""
import numpy as np
from PIL import Image, ImageDraw

from core.media import camera, sfx


def _picture(w, h, spot=(0.75, 0.3)):
    img = Image.new("RGB", (w, h), (90, 90, 90))
    d = ImageDraw.Draw(img)
    x, y, r = spot[0] * w, spot[1] * h, min(w, h) * 0.06
    d.ellipse((x - r, y - r, x + r, y + r), fill=(250, 240, 200))
    return img


def test_interest_finds_the_subject():
    fx, fy = camera.interest(_picture(1600, 900, (0.72, 0.35)))
    assert abs(fx - 0.72) < 0.15 and abs(fy - 0.35) < 0.15


def test_shot_shapes():
    fps = 30
    pano = camera.plan((3000, 1000), (0.8, 0.5), 6, fps, 2560, 0)
    assert [s.kind for s in pano] == ["pan"]
    assert pano[0].end[0] > pano[0].start[0]               # ends on the side of the subject
    assert [s.kind for s in camera.plan((1200, 2000), (0.5, 0.3), 6, fps, 2560, 0)] == ["portrait"]
    assert [s.kind for s in camera.plan((1000, 900), (0.5, 0.8), 6, fps, 2560, 0)] == ["tilt"]


def test_coverage_cuts_to_a_close_up_only_when_long_and_sharp():
    fps = 30
    big_long = camera.plan((4000, 2250), (0.7, 0.4), 8, fps, 2560, 0)
    assert [s.kind for s in big_long] == ["wide", "closeup"]
    assert sum(s.frames for s in big_long) == 240
    close = big_long[1].start
    assert close[2] - close[0] < 4000 / 1.5                  # really closer
    assert [s.kind for s in camera.plan((4000, 2250), (0.7, 0.4), 4, fps, 2560, 0)] == ["wide"]
    assert [s.kind for s in camera.plan((1600, 900), (0.7, 0.4), 8, fps, 2560, 0)] == ["wide"]


def test_boxes_stay_inside_the_picture_and_moves_vary():
    for idx in range(3):
        for shot in camera.plan((4000, 2250), (0.95, 0.05), 8, 30, 2560, idx):
            for x0, y0, x1, y1 in camera.boxes(shot):
                assert -0.01 <= x0 and x1 <= 4000.01 and -0.01 <= y0 and y1 <= 2250.01
                assert abs((x1 - x0) / (y1 - y0) - 16 / 9) < 0.01
    starts = {camera.plan((4000, 2250), (0.7, 0.4), 4, 30, 2560, i)[0].start for i in range(3)}
    assert len(starts) == 3


def test_trim_removes_plain_margins():
    img = Image.new("RGB", (1000, 600), (0, 0, 0))
    inner = _picture(800, 400)
    img.paste(inner, (100, 100))
    out = camera.trim(img)
    assert out.size[0] < 1000 and out.size[1] < 600 and out.size[0] >= 800


def test_sound_design_cues(tmp_path):
    kinds = ["title", None, "map:{}", None, "stat:{}", "stat:{}", None]
    starts = [0, 10, 14, 20, 30, 33, 40]
    ev = sfx.events(kinds, starts)
    assert ev[0] == ("hit", 10)
    names = [e[0] for e in ev]
    assert names.count("whoosh") == 2                       # 33s is too soon after 30s
    path = sfx.track(ev, 45, tmp_path / "sfx.wav")
    from scipy.io import wavfile
    sr, data = wavfile.read(path)
    assert sr == 48000 and data.shape[1] == 2
    peak = np.abs(data).max() / 32767
    assert 0.05 < peak < 0.35                               # well under the voice


def test_directed_segment_renders(tmp_path):
    from core.media.images import source_copy
    from core.media.video import _directed_segment, _ffmpeg_exe
    from core.schemas import Scene
    ff = _ffmpeg_exe()
    if not ff:
        return
    still = tmp_path / "scene_003.jpg"
    _picture(320, 180).save(still)
    _picture(1280, 720).save(source_copy(still))
    s = Scene(index=3, narration="x", visual_prompt="", duration=2.0, image_path=str(still))
    part = tmp_path / "p.mp4"
    assert _directed_segment(ff, s, 3, 2.0, (320, 180), 10, part)
    # the pipeline passes the resolution as a list (settings): must work too
    assert _directed_segment(ff, s, 3, 2.0, [320, 180], 10, tmp_path / "q.mp4")
    assert part.stat().st_size > 1000


def test_cold_open_title_and_hit():
    from core.media.scenes import draw_film_title, film_title
    assert film_title("Meiji Restoration: How Japan Remade Itself", "SHUT FOR 200 YEARS") == "MEIJI RESTORATION"
    assert film_title("How Iceland Ruled Itself Without a King", "NO KING") == "NO KING"
    frame = Image.new("RGB", (640, 360), (120, 120, 120))
    draw_film_title(frame, "MEIJI RESTORATION", (640, 360), 0.2, 10)
    assert frame.getextrema() == ((120, 120), (120, 120), (120, 120))     # not yet
    draw_film_title(frame, "MEIJI RESTORATION", (640, 360), 3.0, 10)
    assert frame.getextrema() != ((120, 120), (120, 120), (120, 120))     # on screen
    ev = sfx.events([None, "map:{}", None], [0, 14, 20], title_at=1.0)
    assert ev[0] == ("hit", 1.0) and ("whoosh", 13.45) in ev
