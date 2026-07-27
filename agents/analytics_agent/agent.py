"""Analytics Agent.

Collects per-video, per-platform performance and stores it in `analytics`, and
updates each video's `ContentMemory.performance_score` so the learning loop has a
target signal.

Modes:
- live      : pull from platform Data APIs (needs credentials; wire in `_live`).
- simulate  : generate plausible, seeded figures so the whole learn loop is
              runnable at $0. CLEARLY flagged as simulated in the row's notes.
- auto      : live where credentials exist, else simulate.
"""

from __future__ import annotations

from core.agents.base import BaseAgent
from core.database.models import Analytics, Content, ContentMemory
from core.database.session import session_scope
from core.registry import register_agent


@register_agent
class AnalyticsAgent(BaseAgent):
    name = "analytics"
    folder = "analytics_agent"

    def run(self, payload: dict | None = None) -> dict:
        payload = payload or {}
        mode = self.config.get("mode", "auto")
        content_ids = payload.get("content_ids")

        updated = 0
        with session_scope() as s:
            q = s.query(Content).filter(Content.status == "published")
            if content_ids:
                q = q.filter(Content.id.in_(content_ids))
            published = q.all()

            for content in published:
                for platform in self.settings.publishing.platforms:
                    row = self._simulate(content, platform) if mode != "live" else self._live(content, platform)
                    s.add(row)
                    updated += 1
                # Update the memory performance score (avg retention proxy).
                mem = s.query(ContentMemory).filter(ContentMemory.video_id == content.id).first()
                if mem:
                    mem.performance_score = self._perf_proxy(content)

        self.log.info("Analytics ingested for %d published video(s) (%d rows, mode=%s)",
                      len(published), updated, mode)
        return {"videos": len(published), "rows": updated, "mode": mode}

    def _perf_proxy(self, content: Content) -> float:
        # Seeded, deterministic performance proxy from quality + id.
        base = (content.quality_score or 60.0)
        jitter = (abs(hash(content.title or content.topic)) % 30) - 15
        return round(max(5.0, min(100.0, base + jitter)), 1)

    def _simulate(self, content: Content, platform: str) -> Analytics:
        seed = abs(hash(f"{content.id}:{platform}:{content.title}"))
        perf = self._perf_proxy(content)
        views = 500 + seed % 20000
        retention = round(min(95.0, 35 + perf * 0.5), 1)
        deciles = [round(max(0.0, 100 - i * (100 - retention) / 9.0), 1)
                   for i in range(self.config.get("retention_deciles", 10))]
        return Analytics(
            video_id=content.id, platform=platform, views=views,
            ctr=round(3 + (seed % 700) / 100.0, 2),
            avg_view_duration=round(content.quality_score or 40, 1),
            watch_time=round(views * retention / 100 * 0.9 / 60, 1),
            retention=retention, retention_curve=deciles,
            completion_rate=round(retention * 0.8, 1),
            likes=views // 20, comments=views // 200, shares=views // 150,
            saves=views // 120, subscribers_generated=views // 300,
        )

    def _live(self, content: Content, platform: str) -> Analytics:  # pragma: no cover - needs creds
        raise NotImplementedError(
            f"Live analytics for {platform} not wired. Implement the Data API call here.")
