"""Publishing Agent.

Uploads the finished video with per-platform metadata. SAFE BY DEFAULT: publishing
is dry-run unless BOTH `publishing.dry_run: false` AND the platform's credentials
are present in the environment. In dry-run it writes a publish manifest so you can
inspect exactly what *would* be posted. Real uploaders live behind per-platform
methods so adding a live integration never touches the pipeline.

DESIGN / SAFETY: this agent never invents credentials and never posts without
them. Going live is an explicit, credential-gated operator decision.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from core.agents.base import BaseAgent
from core.registry import register_agent
from core.schemas import PipelineContext, PublishResult


@register_agent
class PublishingAgent(BaseAgent):
    name = "publishing"
    folder = "publishing_agent"

    def run(self, payload: PipelineContext) -> list[PublishResult]:
        dry_run = self.settings.publishing.dry_run
        cred_map = self.config.get("credential_env", {})
        results: list[PublishResult] = []

        video_path = payload.video.video_path if payload.video else ""
        for meta in payload.metadata:
            platform = meta.platform
            has_creds = all(os.getenv(k) for k in cred_map.get(platform, ["__none__"]))

            if dry_run or not has_creds:
                reason = "dry_run enabled" if dry_run else "missing credentials"
                results.append(PublishResult(
                    platform=platform, status="dry_run",
                    note=f"Would publish '{meta.title}' ({reason}).",
                ))
                continue

            try:
                url = self._publish(platform, video_path, meta)  # pragma: no cover - needs creds
                results.append(PublishResult(platform=platform, status="published", url=url))
            except Exception as exc:
                self.log.error("Publish to %s failed: %s", platform, exc)
                results.append(PublishResult(platform=platform, status="failed", note=str(exc)))

        self._write_manifest(payload, results)
        self.log.info("Publish results: %s", ", ".join(f"{r.platform}={r.status}" for r in results))
        return results

    # ── per-platform uploaders (wire real SDKs here) ───────────────────────
    def _publish(self, platform: str, video_path: str, meta) -> str:  # pragma: no cover
        raise NotImplementedError(
            f"Live upload for {platform} not wired. Install the platform SDK and implement here; "
            f"credentials are read from env: {self.config['credential_env'].get(platform)}")

    def _write_manifest(self, payload: PipelineContext, results: list[PublishResult]) -> None:
        out = Path(self.settings.storage_path("videos")) / f"{payload.run_id}_publish.json"
        manifest = {
            "run_id": payload.run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "video": payload.video.video_path if payload.video else None,
            "metadata": [m.model_dump() for m in payload.metadata],
            "results": [r.model_dump() for r in results],
        }
        out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
