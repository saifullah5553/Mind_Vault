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
  pulls **~9 second excerpts straight from the URL** using HTTP range requests:
  several shots per film, spread across its running time.
- **Each shot is used once**, spread evenly through the video; the scenes in
  between get eye-catching photos (below). Films are interleaved so consecutive
  footage scenes come from different films.
- Only provably clearable, period-appropriate film: items must be in a curated
  public-domain collection or carry an explicit PD/CC licence (community uploads
  in `opensource_movies` no longer count as safe by default), dated 1990 or
  earlier, and not titled like a modern talk, stream or screencast.
- Clips are cover-cropped to frame. Shorts get a burned-in caption overlay;
  long-form keeps a clean picture and ships captions as a track.

## Eye-catching photos

Psychology topics are abstract, so photos are chosen by **mood**, not keyword
(`core/media/themes.py`): narration about goals gets summits and marathons,
hope gets sunrises, the mind gets *The Thinker* or *The School of Athens*,
doubt gets fog and storms, and so on. Each scene takes an unused picture of its
theme. Sources, best first:

1. **Pexels** (if `PEXELS_API_KEY` is set): professional stock, free for
   commercial use.
2. **Wikimedia Commons Featured pictures**, then **Quality images**: hand-reviewed,
   high-resolution, free; matched on the picture's title.
3. **Openverse** large photographs.

Every picture passes a safety filter (nothing sexual, self-harm or gore), a
no-diagrams/no-scans filter, and a 1600 px minimum width. History topics use
literal search, which works well for concrete people, places and events.

## Adding the optional free keys

Both are free and need no card:

1. Pexels — https://www.pexels.com/api/ → add to `.env`:
   `PEXELS_API_KEY=your_key`
2. Pixabay — https://pixabay.com/api/docs/ → add to `.env`:
   `PIXABAY_API_KEY=your_key`

Pexels adds professional modern photos and b-roll, the biggest visual upgrade
for psychology topics. Pixabay adds video b-roll (its free API serves photos only
up to 1280 px, below the HD floor, so it is not used for stills).

## Tuning

`agents/video_agent/config.yaml`:
```yaml
use_stock_footage: true
footage_pool_size: 8       # films searched per video
footage_shots_per_film: 4  # distinct excerpts cut from each film
footage_max_uses: 1        # each shot appears once
```
Set `use_stock_footage: false` to go back to stills only.
Tests set `MIND_VAULT_SKIP_FOOTAGE=1` so they never hit the network.

## Honest limits

- Coverage is patchy for **ancient** history (little PD film of the Maya exists);
  those videos fall back to real photographs, which is usually the better look
  anyway.
- Archival derivatives are low bitrate. They read as authentic archive footage,
  but they are not 4K. Add a Pexels key for crisp modern shots.
