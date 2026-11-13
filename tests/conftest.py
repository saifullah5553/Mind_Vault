"""Pytest fixtures: an isolated in-memory database + offline (stub) config for
every test, so the suite is fast, hermetic, and needs zero external services.
"""

from __future__ import annotations

import os

import pytest

# Force offline/deterministic settings BEFORE anything imports config.
os.environ.setdefault("MIND_VAULT_ENV", "test")
os.environ["MIND_VAULT_DATABASE_URL"] = "sqlite:///:memory:"
# Pin the LLM to the deterministic offline stub so tests never hit a real model
# (Ollama), regardless of what config/settings.yaml is set to.
os.environ["MIND_VAULT_LLM_PROVIDER"] = "stub"


@pytest.fixture(autouse=True, scope="session")
def _empty_test_storage():
    """storage/_test holds only this suite's throwaway output (random run ids).
    It was never cleared and grew to 6 GB, on a disk the real renders need."""
    import shutil
    from pathlib import Path

    from core.config import ROOT_DIR
    target = (ROOT_DIR / "storage" / "_test").resolve()
    if target.parent.name == "storage" and target.name == "_test":
        shutil.rmtree(target, ignore_errors=True)
    yield


@pytest.fixture(autouse=True)
def _fresh_db():
    """Fresh in-memory schema per test, with heavy media disabled for speed.

    Pipeline smoke tests only need the DAG to complete, so we force the fast GIF
    engine and turn off ffmpeg-heavy presenter compositing + music mixing here.
    Those features have their own focused unit tests.
    """
    from core.config import get_settings, reload_settings
    from core.database.session import init_db, reset_engine

    reset_engine()
    s = reload_settings()
    s.video.engine = "gif"
    s.video.background_music = False
    s.presenter.enabled = False
    s.tts.provider = "silence"   # instant, deterministic audio in tests (real Piper is slow)
    s.images.provider = "pillow"  # no network image fetching in tests (hermetic + fast)
    s.video.ken_burns = False     # skip per-scene ffmpeg encodes in tests
    s.video.caption_source = "scenes"  # skip slow whisper transcription in tests

    # Keep test output OUT of the real storage tree. Without this, every test run
    # drops review bundles, videos and images alongside genuine production output.
    for bucket in ("videos", "audio", "images", "thumbnails", "backups"):
        setattr(s.storage, bucket, f"storage/_test/{bucket}")
    s.publishing.review_dir = "storage/_test/review"
    s.storage.root = "storage/_test"  # autopilot lock + state files
    os.environ["MIND_VAULT_LEARNED_RULES"] = "storage/_test/learned_rules.yaml"
    # Skip real Wav2Lip inference in tests (~75s/run); the presenter still returns
    # its portrait + badge, which is what the presenter tests assert on.
    os.environ["MIND_VAULT_SKIP_LIPSYNC"] = "1"
    # No network footage downloads during tests.
    os.environ["MIND_VAULT_SKIP_FOOTAGE"] = "1"
    init_db(drop=True)
    yield
    reset_engine()


@pytest.fixture
def stub_settings():
    from core.config import get_settings
    s = get_settings()
    s.llm.provider = "stub"
    return s


@pytest.fixture(autouse=True)
def _private_ai_cache(tmp_path, monkeypatch):
    """Tests never read or fill the real illustration cache (storage/ai_cache)."""
    from core.media import ai_images
    monkeypatch.setattr(ai_images, "CACHE_DIR", tmp_path / "_ai_cache")
