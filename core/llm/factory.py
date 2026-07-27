"""LLM factory + resilient wrapper.

DESIGN: `get_llm()` reads `settings.llm.provider` and returns the right provider,
wrapped in `ResilientLLM`, which transparently falls back to the offline stub if
the configured provider errors at call time. That guarantees the pipeline NEVER
dies because Ollama isn't running — it degrades to free/offline instead and logs
the fact. Optional paid providers (openai/anthropic) are wired as import-guarded
branches so the base install has zero paid dependencies.
"""

from __future__ import annotations

from functools import lru_cache

from core.config import get_settings
from core.errors import ProviderError
from core.llm.base import LLMMessage, LLMProvider
from core.llm.ollama_provider import OllamaLLM
from core.llm.stub_provider import StubLLM
from core.logging_setup import get_logger

log = get_logger("llm.factory")


class ResilientLLM(LLMProvider):
    """Wraps a primary provider and falls back to a secondary on failure."""

    def __init__(self, primary: LLMProvider, fallback: LLMProvider):
        self.primary = primary
        self.fallback = fallback
        self.name = f"{primary.name}->{fallback.name}"

    def generate(self, messages: list[LLMMessage], *, temperature=None, max_tokens=None) -> str:
        try:
            return self.primary.generate(messages, temperature=temperature, max_tokens=max_tokens)
        except ProviderError as exc:
            log.warning("LLM '%s' failed (%s); falling back to '%s'.",
                        self.primary.name, exc, self.fallback.name)
            return self.fallback.generate(messages, temperature=temperature, max_tokens=max_tokens)


def _build_primary() -> LLMProvider:
    cfg = get_settings().llm
    provider = cfg.provider.lower()

    if provider == "stub":
        return StubLLM()
    if provider == "ollama":
        return OllamaLLM(
            model=cfg.model,
            host_env=cfg.ollama_host_env,
            timeout=cfg.timeout_seconds,
            default_temperature=cfg.temperature,
            default_max_tokens=cfg.max_tokens,
        )
    if provider == "openai":  # optional, import-guarded
        try:
            from core.llm.openai_provider import OpenAILLM  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise ProviderError("openai provider selected but not installed") from exc
        return OpenAILLM(model=cfg.model)
    if provider == "anthropic":  # optional, import-guarded
        try:
            from core.llm.anthropic_provider import AnthropicLLM  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise ProviderError("anthropic provider selected but not installed") from exc
        return AnthropicLLM(model=cfg.model)

    log.warning("Unknown LLM provider %r; using stub.", provider)
    return StubLLM()


@lru_cache(maxsize=1)
def get_llm() -> LLMProvider:
    primary = _build_primary()
    if primary.name == "stub":
        return primary
    # Any real provider gets the offline stub as a safety net.
    return ResilientLLM(primary, StubLLM())


def reset_llm() -> None:
    get_llm.cache_clear()
