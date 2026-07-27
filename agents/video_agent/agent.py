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
        if self.config.get("generate_images", True):
            generate_images(plan.scenes, img_dir)

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
