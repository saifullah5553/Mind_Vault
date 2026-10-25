"""Analytics Agent.

Collects per-video, per-platform performance and stores it in `analytics`, and
updates each video's `ContentMemory.performance_score` so the learning loop has a
target signal.

Modes:
- live / auto : read REAL figures for each real upload (a PlatformPost row)
              from that platform's analytics API. Anything that can't be
              measured (no credentials, no live client for that platform) is
              skipped, never estimated: learning from invented numbers would
              steer the channel by fiction. YouTube is wired; others skip.
- simulate  : generate plausible, seeded figures so the whole learn loop is
              runnable at $0 (demos and tests). Never use it for real decisions.
"""

from __future__ import annotations

from core.agents.base import BaseAgent
from core.database.models import Analytics, Content, ContentMemory, PlatformPost
from core.database.session import session_scope
from core.registry import register_agent


@register_agent
class AnalyticsAgent(BaseAgent):
    name = "analytics"
    folder = "analytics_agent"

    def run(self, payload: dict | None = None) -> dict:
        payload = payload or {}
        mode = payload.get("mode") or self.config.get("mode", "auto")
        content_ids = payload.get("content_ids")

        live_rows = sim_rows = skipped = 0
        with session_scope() as s:
            q = s.query(Content).filter(Content.status == "published")
            if content_ids:
                q = q.filter(Content.id.in_(content_ids))
            published = q.all()

            for content in published:
                if mode == "simulate":
                    rows = [self._simulate(content, p) for p in self.settings.publishing.platforms]
                    sim_rows += len(rows)
                    score = self._perf_proxy(content)
                else:
                    posts = s.query(PlatformPost).filter(PlatformPost.content_id == content.id).all()
                    rows = [r for r in (self._live(content, post) for post in posts) if r]
                    skipped += len(posts) - len(rows)
                    live_rows += len(rows)
                    # Real signal: average retention across platforms we could read.
                    score = (round(sum(r.retention for r in rows) / len(rows), 1)
                             if rows else None)
                s.add_all(rows)
                mem = s.query(ContentMemory).filter(ContentMemory.video_id == content.id).first()
                if mem and score is not None:
                    mem.performance_score = score

        self.log.info("Analytics for %d published video(s): %d live row(s), %d simulated, "
                      "%d skipped (mode=%s)", len(published), live_rows, sim_rows, skipped, mode)
        return {"videos": len(published), "rows": live_rows + sim_rows, "live_rows": live_rows,
                "simulated_rows": sim_rows, "skipped": skipped, "mode": mode}

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

    def _live(self, content: Content, post: PlatformPost) -> Analytics | None:
        """One live row for a real upload, or None if it can't be measured."""
        if post.platform != "youtube":
            return None                       # no live client for this platform yet
        from core.publishing import get_publisher
        if not get_publisher("youtube").is_configured():
            return None
        from core.analytics.youtube import video_report
        from core.errors import ProviderError
        try:
            published = content.published_date.date() if content.published_date else None
            data = video_report(post.external_id, published,
                                deciles=self.config.get("retention_deciles", 10))
        except ProviderError as exc:
            self.log.warning("Live analytics for %s failed: %s", post.external_id, exc)
            return None
        return Analytics(video_id=content.id, platform=post.platform, **data)
