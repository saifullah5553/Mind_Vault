"""Pluggable LLM layer. Import `get_llm()` and never care who the provider is."""

from core.llm.base import LLMProvider, LLMMessage
from core.llm.factory import get_llm

__all__ = ["LLMProvider", "LLMMessage", "get_llm"]
