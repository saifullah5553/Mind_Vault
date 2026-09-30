# Orientation and resolution ("why is the video so small?")

If a rendered video looks like a narrow strip on your monitor, it is **vertical**
— not broken. The pipeline produces two different shapes on purpose:

| Format | Shape | Size | Where it goes |
|---|---|---|---|
| `--format short` | **vertical 9:16** | 1080x1920 | YouTube **Shorts**, TikTok, Instagram Reels |
| `--format long` | **landscape 16:9** | 2560x1440 | normal **YouTube** videos |

`--format short` is the default, which is why early test renders looked small on
a desktop. Vertical is correct for Shorts — it fills a phone screen.

## Controlling it

```bash
# Normal YouTube video, sharp 1440p landscape
python -m scripts.run_pipeline --format long --orientation landscape --resolution 1440
```
```bash
# A SHORT clip but in landscape (16:9) instead of vertical
python -m scripts.run_pipeline --format short --orientation landscape --resolution 1080
```
```bash
# Maximum detail (slow to render)
python -m scripts.run_pipeline --format long --orientation landscape --resolution 4k
```

| `--resolution` | Landscape | Vertical | Notes |
|---|---|---|---|
| `1080` | 1920x1080 | 1080x1920 | fastest |
| `1440` | 2560x1440 | 1440x2560 | **recommended** — YouTube gives 1440p a higher bitrate allowance than 1080p, so it looks cleaner |
| `4k` | 3840x2160 | 2160x3840 | sharpest, slowest to render |

Defaults live in `config/settings.yaml` under `formats:`.

## What actually limits sharpness

Resolution only helps if the *source* has the detail to fill it:

- **Animated scenes** are drawn at the output resolution, so they are sharp at
  any tier including 4K. This is the only source that is truly resolution-free.
- **Photos** are fetched up to 3840px wide, so they hold up at 1440p and 4K.
- **Archival film** is 640x480 at best. Rendering it at 4K does not add detail —
  it just enlarges a soft source. `video.min_footage_height` skips clips too
  small to survive the upscale.

**So for maximum HD:** run animation-led (`animation_max_ratio: 1.0` in
`agents/video_agent/config.yaml`) at `--resolution 1440` or `4k`, and add a free
Pexels/Pixabay key if you want true-HD live footage in the mix.

## Cost of going higher

Render time scales with pixel count. Relative to 1080p: 1440p is roughly 1.8x,
4K roughly 4x. Animation is the heaviest part because every frame is drawn.
