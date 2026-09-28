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
