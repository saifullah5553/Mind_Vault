"""YouTube Audio Library tracks on YouTube only; the generated score on the copies
for Facebook/TikTok (core/media/video.py, scripts/upload_pack.py, make_reels.py)."""
import re
import subprocess

import pytest

from core.media.video import _ffmpeg_exe

ff = _ffmpeg_exe()
pytestmark = pytest.mark.skipif(not ff, reason="ffmpeg not available")


def _probe(path) -> tuple[float, str]:
    info = subprocess.run([ff, "-hide_banner", "-i", str(path)], capture_output=True).stderr.decode(
        "utf-8", "replace")
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", info)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]), info


def _tone(path, seconds, freq=440):
    subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"sine=frequency={freq}:duration={seconds}", "-ac", "2", str(path)], check=True)


def _clip(path, seconds):
    subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size=320x180:rate=10:duration={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=220:duration={seconds}", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)], check=True)


def test_short_track_is_crossfaded_to_length(tmp_path):
    from core.media.video import _long_bed
    _tone(tmp_path / "t.wav", 30)
    out = _long_bed(str(tmp_path / "t.wav"), 70, tmp_path)
    assert out.endswith("_bed_long.wav")
    assert _probe(out)[0] == pytest.approx(71, abs=0.6)
    assert _long_bed(str(tmp_path / "t.wav"), 20, tmp_path) == str(tmp_path / "t.wav")   # long enough


def test_generated_mix_ignores_owner_tracks(tmp_path, monkeypatch):
    from core.config import get_settings
    from core.media import music
    from core.media.video import _mix_music
    (tmp_path / "history").mkdir()
    _tone(tmp_path / "history" / "Calm Piece - Someone.wav", 30)
    monkeypatch.setattr(music, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(get_settings().video, "music_dir", ".")
    base = tmp_path / "base.mp4"
    _clip(base, 8)
    used = _mix_music(base, tmp_path / "yt.mp4", 8, "seed", "history")
    assert used.endswith("Calm Piece - Someone.wav")
    alt = _mix_music(base, tmp_path / "alt.m4a", 8, "seed", "history", generated=True, audio_only=True)
    assert "_generated" in alt
    dur, info = _probe(tmp_path / "alt.m4a")
    assert "Video:" not in info and dur == pytest.approx(8, abs=0.5)


def test_other_platform_copies_get_the_other_audio(tmp_path):
    from scripts.make_reels import _swap_reel_audio
    from scripts.upload_pack import _swap_audio
    video = tmp_path / "v.mp4"
    _clip(video, 6)
    alt = tmp_path / "a.m4a"
    subprocess.run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=880:duration=20",
                    "-c:a", "aac", str(alt)], check=True)
    _swap_audio(video, alt, tmp_path / "fb.mp4")
    assert _probe(tmp_path / "fb.mp4")[0] == pytest.approx(6, abs=0.3)
    _swap_reel_audio(video, alt, 10.0, 4.0, tmp_path / "reel.mp4")
    dur, info = _probe(tmp_path / "reel.mp4")
    assert dur == pytest.approx(6, abs=0.3) and "Audio:" in info     # padded under the card


def test_track_credit():
    from core.media.music import track_credit
    c = track_credit("storage/music/history/Wind-Up Mountains - Schwartzy.mp3")
    assert (c["title"], c["credit"], c["source"]) == ("Wind-Up Mountains", "Schwartzy",
                                                      "YouTube Audio Library")


def test_music_credit_keeps_the_artist_through_the_credits_record(tmp_path):
    """credits.add stores the artist as 'author'; the description must still name it
    (the Japan film's description said 'Listen To Me' with no artist)."""
    from core.media import credits
    from core.media.music import track_credit
    credits.add(tmp_path, [track_credit("x/Listen To Me - Asher Fulero.mp3")], "music")
    m = [i for i in credits.load(tmp_path) if i.get("source") == "YouTube Audio Library"][0]
    assert (m.get("credit") or m.get("author")) == "Asher Fulero"
