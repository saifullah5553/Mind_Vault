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
from core.config import ROOT_DIR
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

        # 2) Photoreal LIP-SYNCED talking clip — Aria actually speaks the narration.
        voice: VoiceResult | None = payload.get("voice")
        run_id = payload.get("run_id", "run")
        provider = self.config.get("lipsync_provider", "auto")
        max_s = float(self.config.get("lipsync_max_seconds", 900))

        import os as _os
        skip = _os.getenv("MIND_VAULT_SKIP_LIPSYNC") == "1"
        if portrait and voice and Path(voice.audio_path).exists() and provider != "none" and not skip:
            if voice.duration > max_s:
                self.log.warning("Narration %.0fs exceeds lipsync_max_seconds (%.0f); "
                                 "using the still badge for this video.", voice.duration, max_s)
            else:
                out = Path(self.settings.storage_path("videos")) / f"presenter_{run_id}.mp4"
                face = self._face_for_lipsync(portrait)
                clip = None
                if provider in ("auto", "sadtalker"):
                    clip = self._sadtalker(face, voice.audio_path, out)
                if clip is None and provider in ("auto", "wav2lip"):
                    clip = self._wav2lip(face, voice.audio_path, out)
                if clip:
                    result["clip"] = clip
                    # Round the talking clip so it matches the circular badge style.
                    round_clip = self._circular_clip(clip)
                    result["overlay"] = round_clip or clip

        kind = "talking clip" if result["clip"] else ("portrait" if result["portrait"] else "none")
        self.log.info("Presenter '%s' ready (%s).", result["persona"], kind)
        return result

    # ── photoreal lip-sync integration points (need GPU + model install) ────
    def _circular_clip(self, clip_path: str) -> str | None:
        """Mask the talking clip into a circle (transparent corners) so the
        presenter reads as a broadcast bug rather than a pasted square."""
        from core.media.video import _ffmpeg_exe  # local import: optional dep
        import subprocess as sp

        ffmpeg = _ffmpeg_exe()
        if not ffmpeg:
            return None
        src = Path(clip_path)
        out = src.with_name(src.stem + "_round.mov")   # .mov/qtrle keeps alpha
        # geq builds a circular alpha mask; qtrle preserves it for the overlay.
        fc = ("format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
              "a='if(lte(hypot(X-(W/2),Y-(H/2)),min(W,H)/2-2),255,0)'")
        try:
            sp.run([ffmpeg, "-y", "-i", str(src), "-vf", fc,
                    "-c:v", "qtrle", "-an", str(out)], check=True, capture_output=True)
            return str(out) if out.exists() else None
        except Exception as exc:
            self.log.warning("Circular clip mask failed (%s); using square clip.", exc)
            return None

    def _face_for_lipsync(self, portrait: str) -> str:
        """Square, downscaled copy of the portrait — Wav2Lip cost scales with size."""
        from PIL import Image
        size = int(self.config.get("lipsync_face_size", 512))
        out = Path(portrait).with_name(f"aria_face{size}.png")
        src = Path(portrait)
        if out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
            return str(out)
        img = Image.open(src).convert("RGB")
        w, h = img.size
        side = min(w, h)
        img = img.crop(((w - side) // 2, (h - side) // 2,
                        (w - side) // 2 + side, (h - side) // 2 + side)).resize((size, size))
        img.save(out)
        return str(out)

    def _run_cmd_template(self, key: str, image: str, audio: str, out: Path) -> str | None:
        """Run a configurable shell command that turns (image, audio) into a talking
        mp4. The command template lives in this agent's config, e.g.:

            sadtalker_cmd: "python /opt/SadTalker/inference.py --source_image {image}
                            --driven_audio {audio} --result_dir {outdir}"

        Placeholders: {image} {audio} {out} {outdir}. Returns the mp4 path or None.
        Kept as a template (not hard-coded) because SadTalker/Wav2Lip are run from
        their own repos with local checkpoint paths that differ per machine.
        """
        import os
        import shlex
        import subprocess

        template = self.config.get(key)
        if not template:
            self.log.info("%s not configured; skipping photoreal talking head. "
                          "Set '%s' in presenter_agent/config.yaml (see docs/SETUP_AI.md).", key, key)
            return None
        out.parent.mkdir(parents=True, exist_ok=True)
        cmd = template.format(image=image, audio=audio, out=str(out), outdir=str(out.parent))
        # Some tools (Wav2Lip) must run from their own directory for relative paths.
        cwd_cfg = self.config.get(key.replace("_cmd", "_cwd"))
        cwd = str(ROOT_DIR / cwd_cfg) if cwd_cfg else None
        # posix=False keeps Windows backslashes intact (posix mode strips them,
        # turning C:\Users\... into C:Users..., which silently breaks the tool).
        argv = shlex.split(cmd, posix=(os.name != "nt"))
        try:
            subprocess.run(argv, check=True, capture_output=True, cwd=cwd)
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
