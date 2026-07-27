"""Typed exceptions and a retry helper shared by every agent.

DESIGN: Distinct exception types let the orchestrator make smart decisions —
e.g. a `QualityGateError` should trigger regeneration, while a `ProviderError`
should trigger a fallback provider, and a `NonRetryableError` should stop
immediately. `with_retry` centralizes backoff so no agent re-implements it.
"""

from __future__ import annotations

import time
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")


class Mind_VaultError(Exception):
    """Base for all Mind_Vault errors."""


class ConfigError(Mind_VaultError):
    """Invalid or missing configuration."""


class ProviderError(Mind_VaultError):
    """An external/pluggable provider (LLM, TTS, image, publish) failed."""


class QualityGateError(Mind_VaultError):
    """Content failed a quality gate and should be regenerated."""


class DuplicateContentError(Mind_VaultError):
    """Content is too similar to something already produced."""


class NonRetryableError(Mind_VaultError):
    """A failure that must not be retried (e.g. bad input, permission denied)."""


def with_retry(
    func: Callable[[], T],
    *,
    retries: int = 3,
    backoff: float = 2.0,
    exceptions: Iterable[type[BaseException]] = (Exception,),
    on_retry: Callable[[int, BaseException], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call ``func`` with exponential backoff.

    ``NonRetryableError`` always aborts immediately regardless of ``exceptions``.
    ``on_retry(attempt, error)`` is invoked before each sleep so callers can log.
    ``sleep`` is injectable for fast tests.
    """
    exc_tuple = tuple(exceptions)
    last: BaseException | None = None
    for attempt in range(1, retries + 1):
        try:
            return func()
        except NonRetryableError:
            raise
        except exc_tuple as exc:  # noqa: PERF203 - clarity over micro-perf
            last = exc
            if attempt >= retries:
                break
            if on_retry:
                on_retry(attempt, exc)
            sleep(backoff * (2 ** (attempt - 1)))
    assert last is not None
    raise last
