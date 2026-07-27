"""Voice Agent.

Thin, swappable wrapper over the free-first TTS layer (`core.media.tts`). The
provider (silence / pyttsx3 / Coqui) is chosen by config, so replacing the voice
engine — including with a premium API later — never touches this agent.
"""

from __future__ import annotations

from pathlib import Path

from core.agents.base import BaseAgent
from core.media.tts import synthesize_speech
from core.registry import register_agent
from core.schemas import Script, VoiceResult


@register_agent
class VoiceAgent(BaseAgent):
    name = "voice"
    folder = "voice_agent"

    def run(self, payload: dict) -> VoiceResult:
        script: Script = payload["script"]
        run_id = payload.get("run_id", "run")
        out = Path(self.settings.storage_path("audio")) / f"{run_id}.wav"

        text = script.full_text
        prefix = self.config.get("narration_prefix", "")
        if prefix:
            text = f"{prefix} {text}"

        result = synthesize_speech(text, out)
        self.log.info("Narration ready via %s (%.1fs)", result.provider, result.duration)
        return result
