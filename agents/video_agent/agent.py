"""Video Editing Engine.

Generates a still per scene (image layer), then assembles narration + stills +
captions into the final video (video layer). Both layers are free-first and
degrade gracefully, so this agent always returns a real, viewable artifact.
"""

from __future__ import annotations

from pathlib import Path

from core.agents.base import BaseAgent
from core.media.images import generate_images
from core.media.video import assemble_video
from core.registry import register_agent
from core.schemas import ScenePlan, VideoResult, VoiceResult


@register_agent
class VideoAgent(BaseAgent):
    name = "video"
    folder = "video_agent"

    def run(self, payload: dict) -> VideoResult:
        plan: ScenePlan = payload["scene_plan"]
        voice: VoiceResult | None = payload.get("voice")
        run_id = payload.get("run_id", "run")
        video_format = payload.get("video_format", "short")

        # Match total video length to the ACTUAL narration length so nothing gets
        # cut off (critical for long-form, where capped scene durations otherwise
        # sum to less than the ~11 min of narration and ffmpeg -shortest truncates).
        if voice and voice.duration and plan.scenes:
            total = sum(max(0.8, s.duration) for s in plan.scenes)
            if total > 0 and abs(total - voice.duration) > 1.0:
                factor = voice.duration / total
                for s in plan.scenes:
                    s.duration = round(max(0.8, s.duration) * factor, 2)
                plan.total_duration = round(sum(s.duration for s in plan.scenes), 2)
                self.log.info("Scaled %d scenes to match narration (%.1fs, x%.2f).",
                              len(plan.scenes), voice.duration, factor)

        img_dir = Path(self.settings.storage_path("images")) / run_id
        fmt = (self.settings.formats.short if video_format == "short"
               else self.settings.formats.long)
        topic = payload.get("topic", "")
        category = payload.get("category", "history")

        # 1) REAL HD FOOTAGE first — the biggest quality lever we have, and it
        #    needs no GPU. Falls back silently to stills when nothing matches.
        import os
        skip_footage = os.getenv("MIND_VAULT_SKIP_FOOTAGE") == "1"
        if self.config.get("use_stock_footage", True) and topic and not skip_footage:
            self._attach_footage(plan.scenes, img_dir, topic, category, fmt.resolution)

        # 2) Stills for any scene without footage (rendered at the video's own
        #    resolution so nothing is letterboxed).
        if self.config.get("generate_images", True):
            self.settings.images.width, self.settings.images.height = fmt.resolution
            generate_images(plan.scenes, img_dir, topic=topic, category=category)

        out = Path(self.settings.storage_path("videos")) / f"{run_id}.mp4"
        presenter_overlay = payload.get("presenter_overlay")
        result = assemble_video(plan.scenes, voice, out, video_format=video_format,
                                presenter_overlay=presenter_overlay)

        # Synced SRT captions (platforms reward them; used by the uploaders).
        if self.settings.video.captions:
            from core.media.captions import build_srt
            srt = build_srt(plan.scenes, Path(self.settings.storage_path("videos")) / f"{run_id}.srt")
            result.srt_path = srt
        self.log.info("Final video: %s via %s (%.1fs)",
                      Path(result.video_path).name, result.engine, result.duration)
        return result

    # ── real footage ────────────────────────────────────────────────────────
    def _attach_footage(self, scenes, out_dir: Path, topic: str, category: str, res) -> None:
        """Download an on-topic clip pool and assign clips + caption overlays."""
        from core.media.images import render_subtitle_overlay
        from core.media.stock_video import fetch_clip_pool

        try:
            want = int(self.config.get("footage_pool_size", 8))
            pool = fetch_clip_pool(topic, want, out_dir, category=category)
        except Exception as exc:
            self.log.warning("Footage fetch failed (%s); using stills.", exc)
            return
        if not pool:
            return

        brand = self.settings.brand.name
        w, h = res
        for scene in scenes:
            clip = pool[scene.index % len(pool)]
            scene.clip_path = clip["path"]
            # Caption rendered once per scene as a transparent PNG.
            scene.overlay_png = render_subtitle_overlay(
                scene.text_overlay or scene.narration, w, h,
                out_dir / f"cap_{scene.index:03d}.png", brand=brand)

        self._write_footage_credits(out_dir, pool)

    def _write_footage_credits(self, out_dir: Path, pool: list[dict]) -> None:
        lines = ["Footage credits (openly licensed):"]
        seen = set()
        for c in pool:
            key = (c.get("title"), c.get("source"))
            if key in seen:
                continue
            seen.add(key)
            who = f" by {c['credit']}" if c.get("credit") else ""
            lines.append(f"- {c.get('title','')}{who} — {c.get('source','')} ({c.get('license','')})")
        try:
            (out_dir / "footage_credits.txt").write_text("\n".join(lines), encoding="utf-8")
        except Exception:
            pass
