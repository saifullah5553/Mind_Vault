"""Configuration loading for Mind_Vault.

DESIGN: One source of truth (`config/settings.yaml`) validated into typed
Pydantic models, with a thin layer of environment-variable overrides for the
handful of values that legitimately differ per machine / per deployment
(environment name, log level, database URL). Secrets are NEVER read from YAML —
only from the environment — so the config file is always safe to commit.

Usage:
    from core.config import get_settings
    settings = get_settings()
    settings.llm.provider          # -> "stub"
    settings.quality.fact_score_min
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Load .env once, as early as possible, so os.environ is populated before we
# apply overrides. Missing .env is fine — everything has a default.
load_dotenv(override=False)

# Repo root = parent of this file's parent (core/ -> repo root).
ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT_DIR / "config" / "settings.yaml"


# ── Typed configuration sections ────────────────────────────────────────────
class BrandConfig(BaseModel):
    name: str = "Mind_Vault"
    tagline: str = ""
    language: str = "en"
    cta: str = ""


class StrategyConfig(BaseModel):
    category_mix: dict[str, float] = Field(default_factory=lambda: {"psychology": 0.5, "history": 0.5})
    calendar_days: int = 90
    avoid_repeat_window: int = 8


class PublishingConfig(BaseModel):
    dry_run: bool = True
    require_manual_approval: bool = True
    short_days: list[str] = Field(default_factory=lambda: ["mon", "wed", "fri"])
    long_days: list[str] = Field(default_factory=lambda: ["sun"])
    platforms: list[str] = Field(default_factory=lambda: ["youtube", "tiktok", "instagram", "facebook"])
    timezone: str = "UTC"
    review_dir: str = "storage/review"


class FormatSpec(BaseModel):
    duration_seconds: list[int] = Field(default_factory=lambda: [45, 75])
    resolution: list[int] = Field(default_factory=lambda: [1080, 1920])
    fps: int = 30


class FormatsConfig(BaseModel):
    short: FormatSpec = Field(default_factory=FormatSpec)
    long: FormatSpec = Field(default_factory=lambda: FormatSpec(duration_seconds=[480, 900], resolution=[1920, 1080]))


class LLMConfig(BaseModel):
    provider: str = "stub"
    model: str = "llama3.1"
    temperature: float = 0.8
    max_tokens: int = 2048
    ollama_host_env: str = "OLLAMA_HOST"
    timeout_seconds: int = 120


class TTSConfig(BaseModel):
    provider: str = "auto"          # auto | piper | coqui | pyttsx3 | silence
    voice: str = "Aria"
    gender: str = "female"
    words_per_minute: int = 155
    piper_model: str = ""           # path to a Piper .onnx voice (female recommended)
    coqui_speaker: str = "Ana Florence"


class ImagesConfig(BaseModel):
    provider: str = "auto"
    style: str = "cinematic documentary"
    width: int = 1024
    height: int = 1024


class VideoConfig(BaseModel):
    engine: str = "auto"
    captions: bool = True
    background_music: bool = True
    music_dir: str = "storage/music"
    music_volume: float = 0.18          # bed level under narration
    music_intro_outro_seconds: float = 4.0  # bed swells louder at start/end


class PresenterConfig(BaseModel):
    enabled: bool = True
    composite: str = "pip"          # pip | full | intro


class QualityConfig(BaseModel):
    fact_score_min: int = 90
    originality_score_min: int = 85
    hook_score_min: int = 80
    duplicate_similarity_max: float = 0.80
    audio_check: bool = True
    visual_check: bool = True
    copyright_risk_max: str = "low"


class DedupConfig(BaseModel):
    method: str = "auto"
    threshold: float = 0.80


class StorageConfig(BaseModel):
    root: str = "storage"
    videos: str = "storage/videos"
    audio: str = "storage/audio"
    images: str = "storage/images"
    thumbnails: str = "storage/thumbnails"
    backups: str = "storage/backups"


class ReliabilityConfig(BaseModel):
    max_retries: int = 3
    retry_backoff_seconds: float = 2.0
    checkpoint: bool = True


class LoggingConfig(BaseModel):
    # `json_logs` maps to the YAML key `json` via alias (avoids shadowing
    # BaseModel.json). Both names work thanks to populate_by_name.
    model_config = {"populate_by_name": True}

    level: str = "INFO"
    dir: str = "logs"
    json_logs: bool = Field(default=False, alias="json")
    rotate_mb: int = 10
    backups: int = 5


class Settings(BaseModel):
    """Top-level typed settings object."""

    env: str = "development"
    database_url: str = f"sqlite:///{(ROOT_DIR / 'mind_vault.db').as_posix()}"

    brand: BrandConfig = Field(default_factory=BrandConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    publishing: PublishingConfig = Field(default_factory=PublishingConfig)
    formats: FormatsConfig = Field(default_factory=FormatsConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    images: ImagesConfig = Field(default_factory=ImagesConfig)
    video: VideoConfig = Field(default_factory=VideoConfig)
    presenter: PresenterConfig = Field(default_factory=PresenterConfig)
    quality: QualityConfig = Field(default_factory=QualityConfig)
    dedup: DedupConfig = Field(default_factory=DedupConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    reliability: ReliabilityConfig = Field(default_factory=ReliabilityConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    # Convenience -----------------------------------------------------------
    def storage_path(self, kind: str) -> Path:
        """Return an absolute Path for a storage bucket ('videos', 'audio', ...)."""
        rel = getattr(self.storage, kind, None)
        if rel is None:
            raise KeyError(f"Unknown storage bucket: {kind!r}")
        p = ROOT_DIR / rel
        p.mkdir(parents=True, exist_ok=True)
        return p

    def ensure_dirs(self) -> None:
        """Create all runtime directories so no agent has to worry about it."""
        for kind in ("videos", "audio", "images", "thumbnails", "backups"):
            self.storage_path(kind)
        (ROOT_DIR / self.logging.dir).mkdir(parents=True, exist_ok=True)


def _apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    """Overlay the small set of env-controlled values onto the YAML dict."""
    if env := os.getenv("MIND_VAULT_ENV"):
        data["env"] = env
    if db := os.getenv("MIND_VAULT_DATABASE_URL"):
        data["database_url"] = db
    if lvl := os.getenv("MIND_VAULT_LOG_LEVEL"):
        data.setdefault("logging", {})["level"] = lvl
    # Let the environment force the LLM provider (tests pin this to 'stub' for
    # determinism regardless of what settings.yaml says).
    if prov := os.getenv("MIND_VAULT_LLM_PROVIDER"):
        data.setdefault("llm", {})["provider"] = prov
    return data


def load_settings(path: str | Path | None = None) -> Settings:
    """Load and validate settings from YAML + environment. Never raises on a
    missing file — falls back to code defaults so the system is always runnable."""
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    raw: dict[str, Any] = {}
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    raw = _apply_env_overrides(raw)
    settings = Settings(**raw)
    settings.ensure_dirs()
    return settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached singleton accessor used everywhere in the app."""
    return load_settings()


def reload_settings() -> Settings:
    """Force a re-read (e.g. after tests mutate config)."""
    get_settings.cache_clear()
    return get_settings()
