"""The generated score, and the thumbnail preferring on-story photos."""
import numpy as np

from core.media import music


def test_score_is_stereo_quiet_and_repeatable():
    a = music.score(12, "iceland")
    b = music.score(12, "iceland")
    assert a.shape == (12 * music.SR, 2)
    assert np.allclose(a, b)
    assert np.max(np.abs(a)) <= 0.9
    rms_db = 20 * np.log10(np.sqrt(np.mean(a ** 2)))
    assert -22 < rms_db < -15
    # It moves: the first and second chord differ.
    first, second = a[2 * music.SR:5 * music.SR, 0], a[10 * music.SR:12 * music.SR, 0]
    assert abs(np.std(first) - np.std(second)) > 0 or not np.allclose(first[:1000], second[:1000])


def test_user_tracks_by_category(tmp_path, monkeypatch):
    from core.config import get_settings
    (tmp_path / "history").mkdir()
    (tmp_path / "history" / "calm.mp3").write_bytes(b"x")
    (tmp_path / "other.mp3").write_bytes(b"x")
    monkeypatch.setattr(music, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(get_settings().video, "music_dir", ".")
    assert [p.name for p in music._user_tracks("history")] == ["calm.mp3"]
    assert [p.name for p in music._user_tracks("psychology")] == ["other.mp3"]


def test_thumbnail_prefers_on_story_photo(tmp_path, monkeypatch):
    from PIL import Image

    from agents.thumbnail_agent.agent import ThumbnailAgent
    folder = tmp_path / "run"
    folder.mkdir()
    Image.new("RGB", (320, 180), (230, 40, 160)).save(folder / "scene_001.jpg")   # colourful
    Image.new("RGB", (320, 180), (120, 120, 110)).save(folder / "scene_002.jpg")  # dull
    agent = ThumbnailAgent.__new__(ThumbnailAgent)
    agent.settings = type("S", (), {"storage_path": staticmethod(lambda _k: str(tmp_path))})()
    agent.log = type("L", (), {"debug": staticmethod(lambda *a: None)})()
    about = {str(folder / "scene_001.jpg"): "Tulip field in spring. The country was rich.",
             str(folder / "scene_002.jpg"): "Law Rock at Thingvellir. The Althing met at the Law Rock."}
    picked = agent._best_photos("run", 1, about=about,
                                story="How Iceland Ruled Itself: The Althing at the Law Rock")
    assert picked[0].name == "scene_002.jpg"
    assert agent._best_photos("run", 1)[0].name == "scene_001.jpg"   # colour only
