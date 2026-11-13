"""Video Editing Engine.

Generates a still per scene (image layer), then assembles narration + stills +
captions into the final video (video layer). Both layers are free-first and
degrade gracefully, so this agent always returns a real, viewable artifact.
"""

from __future__ import annotations

from pathlib import Path

from core.agents.base import BaseAgent
from core.media import credits
from core.media.images import generate_images
from core.media.video import assemble_video, burn_captions
from core.registry import register_agent
from core.schemas import ScenePlan, VideoResult, VoiceResult


def with_disclaimer(scenes: list, video_format: str, brand) -> list:
    """The scenes plus a closing disclaimer card (silent; the music plays on).

    The card is added for rendering only, so chapters and captions still follow
    the narration.
    """
    text = (brand.disclaimer_screen or "").strip()
    if not text or not scenes:
        return list(scenes)
    seconds = brand.disclaimer_seconds_short if video_format == "short" \
        else brand.disclaimer_seconds_long
    card = scenes[-1].model_copy(update={
        "index": scenes[-1].index + 1, "narration": "", "text_overlay": text,
        "duration": seconds, "animation_kind": "notice", "clip_path": None,
        "image_path": None, "sentences": 0})
    return [*scenes, card]


@register_agent
class VideoAgent(BaseAgent):
    name = "video"
    folder = "video_agent"

    def run(self, payload: dict) -> VideoResult:
        plan: ScenePlan = payload["scene_plan"]
        voice: VoiceResult | None = payload.get("voice")
        run_id = payload.get("run_id", "run")
        video_format = payload.get("video_format", "short")

        self._match_narration(plan, voice)

        img_dir = Path(self.settings.storage_path("images")) / run_id
        fmt = (self.settings.formats.short if video_format == "short"
               else self.settings.formats.long)
        topic = payload.get("topic", "")
        category = payload.get("category", "history")
        credits.reset(img_dir)

        # 1) HYBRID: mark the beats that are better ANIMATED than filmed (title,
        #    chapter cards, figures, quotes, date ranges). Decided first, so
        #    footage and photos are spread over the remaining scenes.
        #    Not for Shorts: burned captions already carry the words, and a card
        #    on a plain background is a weak first second to swipe past.
        if self.config.get("use_animation", True) and video_format != "short":
            self._mark_animated(plan.scenes)
        # COLD OPEN: the first line plays over its picture, filmed, with the film's
        # title fading in over it (core/media/scenes.draw_film_title), instead of a
        # text card. A film opens on its strongest image, not on a slide.
        if (video_format != "short" and self.config.get("cold_open", True)
                and plan.scenes and payload.get("title")):
            from core.media.scenes import film_title
            plan.scenes[0].animation_kind = None
            plan.scenes[0].title = film_title(payload["title"], payload.get("thumbnail_text", ""))

        # 2) REAL FOOTAGE: each shot used once, spread through the video.
        import os
        skip_footage = os.getenv("MIND_VAULT_SKIP_FOOTAGE") == "1"
        if self.config.get("use_stock_footage", True) and topic and not skip_footage:
            self._attach_footage(plan.scenes, img_dir, topic, category, fmt.resolution)

        # 3) Eye-catching stills for every other scene (rendered at the video's
        #    own resolution so nothing is letterboxed).
        if self.config.get("generate_images", True):
            self.settings.images.width, self.settings.images.height = fmt.resolution
            generate_images(plan.scenes, img_dir, topic=topic, category=category,
                            subtitles=False, illustrate=payload.get("illustrate", ""))

        if os.getenv("MIND_VAULT_PLAN_ONLY") == "1":
            # The picture plan: the shot list and a sheet of the planned stills,
            # checked BEFORE the long render (scripts.run_pipeline --plan-only).
            from core.errors import NonRetryableError
            from core.media import shotlist
            text, flagged = shotlist.build(plan.scenes, category)
            (img_dir / "picture_plan.txt").write_text(text, encoding="utf-8")
            shotlist.contact_sheet(plan.scenes, img_dir / "picture_plan.jpg")
            self.log.info("Picture plan: %s (%d line(s) flagged)", img_dir / "picture_plan.txt", flagged)
            raise NonRetryableError(f"PLAN ONLY: picture plan written to {img_dir / 'picture_plan.txt'}")

        out = Path(self.settings.storage_path("videos")) / f"{run_id}.mp4"
        presenter_overlay = payload.get("presenter_overlay")
        result = assemble_video(with_disclaimer(plan.scenes, video_format, self.settings.brand),
                                voice, out, video_format=video_format,
                                presenter_overlay=presenter_overlay, category=category)

        if result.music_track:
            from core.media.music import track_credit
            credits.add(img_dir, [track_credit(result.music_track)], "music")

        # Synced SRT captions (platforms reward them; used by the uploaders).
        if self.settings.video.captions:
            from core.media.captions import build_srt, build_srt_from_audio
            srt_out = Path(self.settings.storage_path("videos")) / f"{run_id}.srt"
            srt = None
            # Word-level timings from the rendered narration are far more accurate
            # than durations estimated from the scene plan.
            if voice and self.settings.video.caption_source in ("auto", "audio"):
                spoken = " ".join(s.narration for s in plan.scenes)
                srt = build_srt_from_audio(voice.audio_path, srt_out, script=spoken)
            if not srt:
                srt = build_srt(plan.scenes, srt_out)
            result.srt_path = srt
            # Burned-in captions only where they earn their place: Shorts autoplay
            # muted, so on-screen words matter. Long-form ships a caption track and
            # keeps the picture clean.
            burn = bool(self.config.get("burn_captions", True)) and (
                video_format == "short" or bool(self.config.get("burn_captions_long", False)))
            if burn and srt:
                result.video_path = burn_captions(result.video_path, srt)
        self.log.info("Final video: %s via %s (%.1fs)",
                      Path(result.video_path).name, result.engine, result.duration)
        return result


    def _match_narration(self, plan: ScenePlan, voice: VoiceResult | None) -> None:
        """Make scene timing follow the actual narration so nothing is cut off.

        With per-sentence timings each scene lasts exactly as long as its lines,
        so the picture changes on the voice. Otherwise scale to the total length.
        """
        if not voice or not plan.scenes:
            return
        segs = voice.segments
        if segs and sum(s.sentences for s in plan.scenes) == len(segs):
            i, t = 0, 0.0
            for s in plan.scenes:
                i += s.sentences
                s.duration = round(segs[i - 1]["end"] - t, 3)
                t = segs[i - 1]["end"]
            plan.total_duration = round(t, 2)
            self.log.info("Cut %d scenes on the voice's sentence timings (%.1fs).",
                          len(plan.scenes), t)
            return
        total = sum(max(0.8, s.duration) for s in plan.scenes)
        if voice.duration and total > 0 and abs(total - voice.duration) > 1.0:
            factor = voice.duration / total
            for s in plan.scenes:
                s.duration = round(max(0.8, s.duration) * factor, 2)
            plan.total_duration = round(sum(s.duration for s in plan.scenes), 2)
            self.log.info("Scaled %d scenes to match narration (%.1fs, x%.2f).",
                          len(plan.scenes), voice.duration, factor)

    # ── hybrid animation ────────────────────────────────────────────────────
    def _mark_animated(self, scenes) -> None:
        """Flag scenes that suit motion graphics, capped so the video stays mixed."""
        from core.media.animation import choose_kind

        max_ratio = float(self.config.get("animation_max_ratio", 0.5))
        budget = max(1, int(round(len(scenes) * max_ratio)))
        used = 0

        # Chapter headings always get a title card; they don't use the budget.
        from core.media.spoken import CHAPTER_RE
        for scene in scenes:
            if CHAPTER_RE.match(scene.narration.strip()):
                scene.animation_kind = "title"

        # Pass 0 — maps: the first line naming each place or country shows where
        # it is (core/media/maps.py). They count towards the budget.
        if self.config.get("maps", True):
            import json

            from core.media.maps import plan_maps
            try:
                plan = plan_maps([s.narration for s in scenes],
                                 limit=int(self.config.get("map_max", 4)))
            except Exception as exc:
                self.log.warning("Map planning failed (%s); no maps.", str(exc)[:160])
                plan = {}
            for i, spec in plan.items():
                if not scenes[i].animation_kind and used < budget:
                    scenes[i].animation_kind = "map:" + json.dumps(spec)
                    used += 1
            if plan:
                self.log.info("Maps: %s", ", ".join(s["place"] or s["country"]
                                                   for s in plan.values()))

        # Pass 0b — digging, buried finds and dating: animated soil layers
        # (core/media/scenes.py). At most two, well apart.
        if self.config.get("layers", True):
            import json

            from core.media.scenes import layers_for
            last = -99
            for i, scene in enumerate(scenes):
                if i == 0 or scene.animation_kind or used >= budget or i - last < 8:
                    continue
                spec = layers_for(scene.narration)
                if spec and sum(1 for s in scenes if (s.animation_kind or "").startswith("layers:")) < 2:
                    scene.animation_kind = "layers:" + json.dumps(spec)
                    used += 1
                    last = i

        # Pass 1 — confident matches (a headline, a figure, a date range, a
        # cause->effect chain). These are the scenes animation renders best.
        shown = {s.text_overlay.lower() for s in scenes if s.animation_kind}
        for i, scene in enumerate(scenes):
            if scene.animation_kind:
                continue
            if used >= budget:
                break
            kind = choose_kind(scene.narration, i, is_first=(i == 0))
            # The same card twice in one video looks like a mistake.
            if kind and scene.text_overlay.lower() not in shown:
                scene.animation_kind = kind
                shown.add(scene.text_overlay.lower())
                used += 1

        # Pass 2 — fill the remaining budget with generic kinds. Without this,
        # raising animation_max_ratio has almost no effect, because pass 1 only
        # fires on scenes with an explicit signal. Filling matters for maximum
        # HD: animated frames are drawn at the output resolution, whereas
        # archival footage is 640x480 and cannot be sharpened by upscaling.
        if self.config.get("animation_fill", True) and used < budget:
            generic = ["bullets", "ambient", "concept", "ambient"]
            gi = 0
            for i, scene in enumerate(scenes):
                if used >= budget:
                    break
                if scene.animation_kind:
                    continue
                scene.animation_kind = generic[gi % len(generic)]
                gi += 1
                used += 1

        total = sum(1 for s in scenes if s.animation_kind)
        if total:
            self.log.info("Animating %d/%d scene(s) as motion graphics.", total, len(scenes))

    # ── real footage ────────────────────────────────────────────────────────
    def _attach_footage(self, scenes, out_dir: Path, topic: str, category: str, res) -> None:
        """Download distinct shots and give each to ONE scene, spread evenly.

        Cycling a 7-clip pool across ~80 scenes showed every SD shot about 12
        times. Now each shot is used once (footage_max_uses) and the scenes in
        between get HD photos.
        """
        from core.media.stock_video import fetch_clip_pool

        # The first line naming a person/place keeps its still: the actual
        # subject (Rembrandt's Aristotle) beats generic b-roll there.
        from core.media.themes import known_names, named_subjects
        known = known_names(" ".join(s.narration for s in scenes))
        seen_names: set[str] = set()
        free = []
        for s in scenes:
            if s.animation_kind or s.title:      # the cold open is a filmed still
                continue
            new = [n for n in named_subjects(s.narration, known) if n not in seen_names]
            seen_names.update(new)
            seen_names.update(n.split()[-1] for n in new)    # "Harlow" = "Harry Harlow"
            if not new:
                free.append(s)
        # Subject b-roll (reading, friends, walking...) illustrates psychology ideas.
        # Over a history line it puts a dog or a guitarist where the place should be.
        if category == "psychology":
            free = self._attach_subject_clips(free, out_dir, res)
        if not free:
            return
        w, h = res
        themed = category == "psychology"
        try:
            want = int(self.config.get("footage_pool_size_themed" if themed
                                       else "footage_pool_size", 8))
            want = min(want, len(free))      # a 13-scene Short needs 13 clips, not 48
            pool = fetch_clip_pool(topic, want, out_dir, category=category,
                                   shots_per_film=int(self.config.get("footage_shots_per_film", 4)),
                                   # 1080p stock is plentiful and upscales cleanly
                                   # to 1440p (1.33x); demanding 1440p left gaps
                                   # that 480p archive reels filled.
                                   landscape=w > h, min_height=min(1080, w, h))
        except Exception as exc:
            self.log.warning("Footage fetch failed (%s); using stills.", exc)
            return
        if not pool:
            return

        uses = max(1, int(self.config.get("footage_max_uses", 1)))
        shots = (pool * uses)[:len(free)]
        step = len(free) / len(shots)
        remaining = list(shots)
        placed: list[dict] = []
        from core.media.stock import part_per_line
        line_part = dict(zip(map(id, scenes), part_per_line([s.narration for s in scenes], topic)))
        if category == "history":
            from core.media.stock import relevance
            placed = []
            taken: set[int] = set()
            for clip in shots:
                fits = [(relevance(s.narration, {"title": clip.get("title", "")})[0], -n, n)
                        for n, s in enumerate(free) if n not in taken and not s.clip_path
                        and ("part" not in clip or line_part.get(id(s)) == clip["part"])]
                best = max(fits, default=None)
                if not best or best[0] < 2:
                    continue          # no line this shot shows: the lines keep stills
                scene = free[best[2]]
                taken.update({best[2] - 1, best[2], best[2] + 1})   # not back to back
                scene.clip_path = clip["path"]
                scene.source = "footage: " + str(clip.get("title", ""))[:110]
                placed.append(clip)
            self.log.info("Footage: %d of %d shot(s) fit a line and were placed.",
                          len(placed), len(shots))
            credits.add(out_dir, placed, "footage")
            return
        for k in range(len(shots)):
            scene = free[int(k * step)]
            # Evenly spread positions; at each, footage of the part of the story
            # this line is in, else the clip whose mood fits the line.
            same = [c for c in remaining if c.get("part") == line_part.get(id(scene))]
            if not same and any("part" in c for c in remaining):
                continue      # no footage of this part left: the line keeps a still
            clip = same[0] if same else self._best_clip(scene.narration, remaining)
            remaining.remove(clip)
            scene.clip_path = clip["path"]
            scene.source = "footage: " + str(clip.get("title", ""))[:110]
            placed.append(clip)
        self.log.info("Footage: %d distinct shot(s) placed across %d scene(s).",
                      len(pool), len(placed))
        credits.add(out_dir, placed, "footage")

    def _attach_subject_clips(self, scenes, out_dir: Path, res) -> list:
        """Lines about something concrete show that thing. Returns the scenes left."""
        from collections import Counter

        from core.media.stock_video import fetch_subject_clips
        from core.media.themes import carry_subjects

        subjects = dict(zip(map(id, scenes), carry_subjects([s.narration for s in scenes])))
        wanted = Counter(q for q in subjects.values() if q)
        if not wanted:
            return scenes
        w, h = res
        try:
            found = fetch_subject_clips(dict(wanted), out_dir, landscape=w > h,
                                        min_height=min(1080, w, h))
        except Exception as exc:
            self.log.warning("Subject footage failed (%s).", exc)
            return scenes
        rest, placed = [], []
        for s in scenes:
            clips = found.get(subjects[id(s)] or "", [])
            if clips:
                clip = clips.pop(0)
                s.clip_path = clip["path"]
                s.source = "footage: " + str(clip.get("title", ""))[:110]
                placed.append(clip)
            else:
                rest.append(s)
        credits.add(out_dir, placed, "footage")
        return rest

    @staticmethod
    def _best_clip(text: str, clips: list[dict]) -> dict:
        """A clip of the scene's theme if one is left, else the next clip."""
        if any("theme" in c for c in clips):
            from core.media.themes import theme_of
            theme = theme_of(text)
            for c in clips:
                if c.get("theme") == theme:
                    return c
        return clips[0]
