# Animated motion graphics (free, CPU-only, no GPU)

Answering "can we do animated cartoon videos?" — yes, but not via AI video
generators. Those have no free API, allow only a handful of clips per day, and
automating their web UIs breaks their terms. Consistent cartoon *characters* also
need a GPU (Stable Diffusion + LoRA) or a human designer.

What works instead is what the biggest channels in this niche actually use:
**flat vector motion graphics generated in code** (the Kurzgesagt look, not
character cartoons). Engine: `core/media/animation.py`, built on Pillow + ffmpeg
only — no Manim, no cairo, no LaTeX.

## Why this is the strong option

- **No GPU, no cost, no rate limits** — it is just drawing.
- **Zero copyright risk** — every pixel is generated here.
- **Always on-topic.** Archival film of the Maya does not exist; an animated map
  or timeline of the Maya does, instantly. This closes the coverage gap that
  footage alone leaves for ancient history.
- **Fully automatable**, which is the point of the whole system.

## Scene kinds

| Kind | Used when | Looks like |
|---|---|---|
| `title` | the opening hook | big kinetic headline + accent rule drawing in |
| `stat` | text contains a number or percentage | number counting up over a filling bar |
| `timeline` | two or more dates | a line drawing itself, date ticks popping in |
| `concept` | cause/effect wording ("because", "led to") | nodes connected by arrows drawing in sequence |
| `quote` | quoted text | quotation revealing line by line |
| `bullets` | several short clauses | points sliding in one at a time |
| `ambient` | fallback when nothing else fits | drifting shapes behind the caption |

The kind is chosen from the narration by `choose_kind()` — no LLM call needed.

## Hybrid behaviour

`agents/video_agent/config.yaml`:

```yaml
use_animation: true
animation_max_ratio: 0.5   # at most half the scenes animated
```

Per scene the builder tries, in order: **animation** (if the beat suits it) →
**real archival footage** → **cinematic still**. The cap keeps the video mixed
rather than wall-to-wall graphics. Set `use_animation: false` for footage only,
or raise the ratio to 1.0 for a fully animated channel.

## Performance

Roughly **4–5 s of CPU per 3 s scene** at 1080x1920/30fps. The background
gradient is computed once per scene with numpy and reused for every frame, and
frames are written as JPEG (much faster to encode than PNG).

## Restyling the brand

Colours and fonts live in the `Style` dataclass in `core/media/animation.py`
(`bg_top`, `bg_bottom`, `accent`, `ink`, `muted`, `palette`). Change them once and
every animated scene follows.

## Honest limits

- This is **flat vector motion graphics**, not Pixar/anime character animation.
- **No recurring mascot character** with acting/expressions — that needs a GPU or
  a designer.
- Kind detection is heuristic, so it will occasionally pick an odd style; the
  `ambient` fallback keeps it safe.

## Output quality — measured, not assumed

| Layer | Native resolution | Genuinely HD? |
|---|---|---|
| **Animation** | rendered at the full frame (1080x1920 / 1920x1080) | **Yes — crisp, near-lossless** |
| **Photos** (Wikimedia/Openverse) | large originals, requested at 1600px | **Yes** |
| **Archival footage** (Internet Archive) | **640x480 at best** | **No — inherently SD** |
| **Pexels / Pixabay** (free key) | 1080p–4K | **Yes** |

Two things are worth understanding:

**Animated scenes have a low bitrate and that is fine.** Flat vector graphics
contain very little detail, so x264 at CRF 18 reproduces them essentially
losslessly at a few hundred kbps. Bitrate is only a meaningful quality signal for
noisy, grainy sources like film.

**Archival film will never be HD.** These are scans of mid-20th-century reels;
the best derivative the Internet Archive offers is typically 640x480. Upscaled to
a 1080p frame it looks soft and dated. Two guards exist:

- `video.min_footage_height` (default 400) rejects sources too small to upscale;
  that beat falls back to a high-resolution photo or an animated scene instead.
- The fetcher now picks the **highest-resolution** derivative available. (An
  earlier version picked the smallest file to save bandwidth, which produced
  320x240 sources — visibly bad. Since we only range-read a few seconds, file
  size is irrelevant and quality wins.)

### Dials

`config/settings.yaml`:
```yaml
video:
  crf: 18            # lower = better quality (18 ~ visually lossless); 23 = faster/smaller
  preset: "medium"   # slower preset = better quality per bitrate
  frame_quality: 95  # JPEG quality of generated animation frames
  min_footage_height: 400
```

### If you want everything to be true HD

Archival footage is the only SD element. Either:

1. **Go animation-heavy** — set `animation_max_ratio: 1.0` in
   `agents/video_agent/config.yaml`. Every frame is then generated at native
   resolution and is genuinely HD, at zero cost.
2. **Add a free Pexels/Pixabay key** — real 1080p/4K stock video (see
   [FOOTAGE.md](FOOTAGE.md)).
