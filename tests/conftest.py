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
    init_db(drop=True)
    yield
    reset_engine()


@pytest.fixture
def stub_settings():
    from core.config import get_settings
    s = get_settings()
    s.llm.provider = "stub"
    return s
