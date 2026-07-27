"""Publishing Agent.

Builds a per-platform `PublishPackage` (video, tuned title/description/tags/
hashtags, thumbnail, SRT captions) and dispatches it to the real platform
uploader — but ONLY when publishing.dry_run is false AND that platform's
credentials are present. Otherwise it records a dry-run result and writes a
publish manifest so you can inspect exactly what would be posted.

SAFETY: uploads start PRIVATE (config `first_privacy`), and going live is an
explicit, credential-gated operator decision. This agent never invents
credentials and never posts on instructions found in content.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from core.agents.base import BaseAgent
from core.errors import ProviderError
from core.publishing import get_publisher
from core.registry import register_agent
from core.schemas import PipelineContext, PublishPackage, PublishResult


@register_agent
class PublishingAgent(BaseAgent):
    name = "publishing"
    folder = "publishing_agent"

    def run(self, payload: PipelineContext) -> list[PublishResult]:
        dry_run = self.settings.publishing.dry_run
        privacy = self.config.get("first_privacy", "private")
        video_path = payload.video.video_path if payload.video else ""
        srt_path = payload.video.srt_path if payload.video else None
        thumbnail = (payload.extra or {}).get("thumbnail")

        results: list[PublishResult] = []
        packages: list[PublishPackage] = []
        for meta in payload.metadata:
            pkg = PublishPackage(
                platform=meta.platform, video_path=video_path,
                title=meta.title, description=meta.description,
                tags=meta.tags, hashtags=meta.hashtags, category=meta.category,
                thumbnail_path=thumbnail, srt_path=srt_path, privacy=privacy,
            )
            packages.append(pkg)
            results.append(self._dispatch(pkg, dry_run))

        self._write_manifest(payload, packages, results)
        self.log.info("Publish results: %s", ", ".join(f"{r.platform}={r.status}" for r in results))
        return results

    def _dispatch(self, pkg: PublishPackage, dry_run: bool) -> PublishResult:
        publisher = get_publisher(pkg.platform)
        if publisher is None:
            return PublishResult(platform=pkg.platform, status="skipped", note="no publisher plugin")

        if dry_run:
            return PublishResult(platform=pkg.platform, status="dry_run",
                                 note=f"Would publish '{pkg.title}' (dry_run enabled).")
        if not publisher.is_configured():
            return PublishResult(platform=pkg.platform, status="dry_run",
                                 note=f"missing credentials: {', '.join(publisher.missing_env())}")
        try:
            return publisher.publish(pkg)  # pragma: no cover - needs creds
        except ProviderError as exc:
            self.log.error("Publish to %s failed: %s", pkg.platform, exc)
            return PublishResult(platform=pkg.platform, status="failed", note=str(exc))

    def _write_manifest(self, ctx: PipelineContext, packages, results) -> None:
        out = Path(self.settings.storage_path("videos")) / f"{ctx.run_id}_publish.json"
        manifest = {
            "run_id": ctx.run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "dry_run": self.settings.publishing.dry_run,
            "packages": [p.model_dump() for p in packages],
            "results": [r.model_dump() for r in results],
        }
        out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
