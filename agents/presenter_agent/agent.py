"""AI Presenter Agent.

Produces a CONSISTENT, fictional female presenter ("Aria" by default) for the
brand and returns the asset the video stage composites in.

ETHICS / TRANSPARENCY:
- The presenter is a fully AI-generated, fictional persona (a person who does NOT
  exist). This agent generates her synthetic face from a fixed seed; it never
  ingests or imitates a real, identifiable individual.
- The persona is disclosed as AI-generated (`disclosure`), surfaced by the SEO
  agent into the video description for platform compliance.

Free-first, graceful degradation:
- Portrait: Stable Diffusion (photoreal, needs GPU) → tasteful stylized card ($0).
- Talking clip: SadTalker/Wav2Lip (photoreal lip-sync, needs GPU) → none, in which
  case the video stage composites the still portrait (a consistent presenter, not
  a fake talking video). Nothing here ever breaks the pipeline.

Returns: {"portrait": path|None, "clip": path|None, "overlay": path|None,
          "disclosure": str, "persona": str}
"""

from __future__ import annotations

from pathlib import Path

from core.agents.base import BaseAgent
from core.media.avatar import get_presenter_portrait
from core.registry import register_agent
from core.schemas import VoiceResult


@register_agent
class PresenterAgent(BaseAgent):
    name = "presenter"
    folder = "presenter_agent"

    def run(self, payload: dict) -> dict:
        persona = self.config.get("persona", {})
        disclosure = self.config.get("disclosure", "Narrated by an AI-generated presenter.")
        result = {"portrait": None, "clip": None, "overlay": None,
                  "disclosure": disclosure, "persona": persona.get("name", "Aria")}

        if not self.config.get("enabled", True):
            self.log.info("Presenter disabled; video will be a narrated slideshow.")
            return result

        # 1) Her consistent synthetic portrait (generated once, then cached).
        portrait = get_presenter_portrait(
            appearance=persona.get("appearance", "a young adult woman, friendly, photorealistic"),
            name=persona.get("name", "Aria"),
            seed=int(persona.get("seed", 776633)),
            portrait_path=self.config.get("portrait_path", "storage/presenter/aria.png"),
            provider=self.config.get("avatar_provider", "auto"),
        )
        result["portrait"] = portrait
        result["overlay"] = portrait  # default: composite the still portrait

        # Prefer a circular, transparent PiP badge — reads as a broadcast presenter
        # rather than a pasted rectangle. The raw portrait is kept for lip-sync.
        if portrait and self.config.get("pip_badge", True):
            from core.media.avatar import make_pip_badge
            badge = make_pip_badge(portrait, Path(portrait).with_name("aria_pip.png"))
            if badge:
                result["overlay"] = badge

        # 2) Optional photoreal talking clip (GPU pipelines).
        voice: VoiceResult | None = payload.get("voice")
        run_id = payload.get("run_id", "run")
        provider = self.config.get("lipsync_provider", "auto")
        if portrait and voice and Path(voice.audio_path).exists() and provider in ("auto", "sadtalker", "wav2lip"):
            out = Path(self.settings.storage_path("videos")) / f"presenter_{run_id}.mp4"
            clip = None
            if provider in ("auto", "sadtalker"):
                clip = self._sadtalker(portrait, voice.audio_path, out)
            if clip is None and provider in ("auto", "wav2lip"):
                clip = self._wav2lip(portrait, voice.audio_path, out)
            if clip:
                result["clip"] = clip
                result["overlay"] = clip  # prefer the talking clip if we made one

        kind = "talking clip" if result["clip"] else ("portrait" if result["portrait"] else "none")
        self.log.info("Presenter '%s' ready (%s).", result["persona"], kind)
        return result

    # ── photoreal lip-sync integration points (need GPU + model install) ────
    def _run_cmd_template(self, key: str, image: str, audio: str, out: Path) -> str | None:
        """Run a configurable shell command that turns (image, audio) into a talking
        mp4. The command template lives in this agent's config, e.g.:

            sadtalker_cmd: "python /opt/SadTalker/inference.py --source_image {image}
                            --driven_audio {audio} --result_dir {outdir}"

        Placeholders: {image} {audio} {out} {outdir}. Returns the mp4 path or None.
        Kept as a template (not hard-coded) because SadTalker/Wav2Lip are run from
        their own repos with local checkpoint paths that differ per machine.
        """
        import shlex
        import subprocess

        template = self.config.get(key)
        if not template:
            self.log.info("%s not configured; skipping photoreal talking head. "
                          "Set '%s' in presenter_agent/config.yaml (see docs/SETUP_AI.md).", key, key)
            return None
        out.parent.mkdir(parents=True, exist_ok=True)
        cmd = template.format(image=image, audio=audio, out=str(out), outdir=str(out.parent))
        try:
            subprocess.run(shlex.split(cmd), check=True, capture_output=True)
            # Some tools write into result_dir with their own name; accept the newest mp4.
            if out.exists():
                return str(out)
            mp4s = sorted(out.parent.glob("*.mp4"), key=lambda p: p.stat().st_mtime)
            return str(mp4s[-1]) if mp4s else None
        except Exception as exc:
            self.log.warning("%s failed (%s).", key, exc)
            return None

    def _sadtalker(self, image: str, audio: str, out: Path) -> str | None:  # pragma: no cover
        """SadTalker: image + audio -> photoreal talking head (GPU).
        Install: https://github.com/OpenTalker/SadTalker ; set `sadtalker_cmd`."""
        return self._run_cmd_template("sadtalker_cmd", image, audio, out)

    def _wav2lip(self, image: str, audio: str, out: Path) -> str | None:  # pragma: no cover
        """Wav2Lip: drive lip movement on the portrait (GPU).
        Install: https://github.com/Rudrabha/Wav2Lip ; set `wav2lip_cmd`."""
        return self._run_cmd_template("wav2lip_cmd", image, audio, out)
