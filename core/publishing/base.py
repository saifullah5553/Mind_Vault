"""Publisher interface.

DESIGN: One tiny interface per platform. `is_configured()` reports whether the
required credentials (env vars / GitHub Secrets) are present, so the Publishing
agent can decide dry-run vs. real upload WITHOUT the platform code ever running
prematurely. Credentials are read from the environment only — never stored in
code or YAML.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod

from core.logging_setup import get_logger
from core.schemas import PublishPackage, PublishResult


class PlatformPublisher(ABC):
    platform: str = "base"
    required_env: list[str] = []

    def __init__(self) -> None:
        self.log = get_logger(f"publish.{self.platform}")

    def is_configured(self) -> bool:
        return bool(self.required_env) and all(os.getenv(k) for k in self.required_env)

    def missing_env(self) -> list[str]:
        return [k for k in self.required_env if not os.getenv(k)]

    @abstractmethod
    def publish(self, pkg: PublishPackage) -> PublishResult:
        """Upload the video. Only called when is_configured() and not dry_run."""
