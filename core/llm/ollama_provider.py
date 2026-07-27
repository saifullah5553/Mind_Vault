"""Ollama provider — the recommended FREE local LLM (https://ollama.com).

DESIGN: Ollama runs open models (llama3.1, mistral, qwen, gemma) locally with a
simple HTTP API and no API key. This provider talks to it over httpx. If Ollama
isn't running/installed, `generate` raises `ProviderError`, and the factory /
agent retry layer falls back to the stub — so a missing local model never breaks
a run. `is_available()` / `installed_models()` power the `doctor` diagnostics.
"""

from __future__ import annotations

import json
import os

import httpx

from core.errors import ProviderError
from core.llm.base import LLMMessage, LLMProvider


class OllamaLLM(LLMProvider):
    name = "ollama"

    def __init__(self, model: str, host_env: str = "OLLAMA_HOST", timeout: int = 120,
                 default_temperature: float = 0.8, default_max_tokens: int = 2048):
        self.model = model
        self.host = os.getenv(host_env) or "http://localhost:11434"
        self.timeout = timeout
        self.default_temperature = default_temperature
        self.default_max_tokens = default_max_tokens

    # ── diagnostics ─────────────────────────────────────────────────────────
    def is_available(self) -> bool:
        try:
            httpx.get(f"{self.host}/api/tags", timeout=4).raise_for_status()
            return True
        except Exception:
            return False

    def installed_models(self) -> list[str]:
        try:
            r = httpx.get(f"{self.host}/api/tags", timeout=4)
            r.raise_for_status()
            return [m.get("name", "") for m in r.json().get("models", [])]
        except Exception:
            return []

    # ── generation ───────────────────────────────────────────────────────────
    def _chat(self, messages, temperature, max_tokens, fmt=None) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "options": {
                "temperature": self.default_temperature if temperature is None else temperature,
                "num_predict": self.default_max_tokens if max_tokens is None else max_tokens,
            },
        }
        if fmt:
            payload["format"] = fmt  # Ollama native structured output, e.g. "json"
        try:
            resp = httpx.post(f"{self.host}/api/chat", json=payload, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()["message"]["content"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise ProviderError(f"Ollama request failed ({self.host}, model={self.model}): {exc}") from exc

    def generate(self, messages: list[LLMMessage], *, temperature=None, max_tokens=None) -> str:
        return self._chat(messages, temperature, max_tokens)

    def generate_json(self, messages: list[LLMMessage], *, temperature=None, max_tokens=None):
        """Use Ollama's native JSON mode for reliable structured output."""
        raw = self._chat(messages, temperature, max_tokens, fmt="json")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return self._extract_json(raw)
