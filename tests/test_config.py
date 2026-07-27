from core.config import get_settings


def test_settings_load_and_defaults():
    s = get_settings()
    assert s.brand.name == "Mind_Vault"
    # Category mix should sum to ~1.0.
    assert abs(sum(s.strategy.category_mix.values()) - 1.0) < 1e-6
    assert s.quality.duplicate_similarity_max == 0.80
    assert s.llm.provider in ("stub", "ollama", "openai", "anthropic")


def test_storage_paths_created(tmp_path):
    s = get_settings()
    p = s.storage_path("videos")
    assert p.exists() and p.is_dir()


def test_env_override_database(monkeypatch):
    # conftest sets an in-memory DB via env; confirm it took effect.
    assert ":memory:" in get_settings().database_url
