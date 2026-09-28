# Real HD footage (free, no GPU, no API key)

Static images are what made early output look like a slideshow. The pipeline now
uses **real moving footage** wherever it can find a clearable clip, and falls
back to the cinematic still treatment otherwise.

## Sources

| Source | Key needed | Best for |
|---|---|---|
| **Internet Archive** | none | public-domain archival film — history |
| **Wikimedia Commons** | none | CC/PD video |
| **Pexels Videos** | free key | modern b-roll, psychology, 4K |
| **Pixabay Videos** | free key | broad HD library |

Works out of the box with the two keyless sources.

## Copyright safety (important)

The Internet Archive hosts plenty of uploads that are **not** clearable (TV
documentaries, feature films). Putting those in a monetised video earns copyright
strikes. So an item is accepted **only** when its metadata proves it is public
domain or Creative Commons — either it lives in a known-safe collection
(`prelinger`, `publicmovies`, `opensource_movies`, `nasa`, `usnationalarchives`,
`universallibrary`) or its `licenseurl`/`rights` field matches a PD/CC pattern.
Everything used is credited in `footage_credits.txt` beside the rendered video.

## How clips are fetched

- **One topic-level search per video** (not per scene), so the footage stays
  visually coherent and on-subject.
- Archive films are hundreds of MB, so we never download them. `ffmpeg -ss`
  pulls a **~9 second excerpt straight from the URL** using HTTP range requests,
  at staggered offsets so several excerpts from one film look different.
- Clips are cover-cropped to frame, captioned with a transparent PNG overlay
  (avoids ffmpeg `drawtext` escaping problems), and looped if short.

## Adding the optional free keys

Both are free and need no card:

1. Pexels — https://www.pexels.com/api/ → add to `.env`:
   `PEXELS_API_KEY=your_key`
2. Pixabay — https://pixabay.com/api/docs/ → add to `.env`:
   `PIXABAY_API_KEY=your_key`

This noticeably improves coverage for psychology/modern topics, where archival
film is thin.

## Tuning

`agents/video_agent/config.yaml`:
```yaml
use_stock_footage: true
footage_pool_size: 8     # clips per video, cycled across scenes
```
Set `use_stock_footage: false` to go back to stills only.
Tests set `MIND_VAULT_SKIP_FOOTAGE=1` so they never hit the network.

## Honest limits

- Coverage is patchy for **ancient** history (little PD film of the Maya exists);
  those videos fall back to real photographs, which is usually the better look
  anyway.
- Archival derivatives are low bitrate. They read as authentic archive footage,
  but they are not 4K. Add a Pexels key for crisp modern shots.
