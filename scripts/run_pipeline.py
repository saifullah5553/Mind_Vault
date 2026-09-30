"""Run the Mind_Vault production pipeline once, end-to-end.

Usage:
    python -m scripts.run_pipeline
    python -m scripts.run_pipeline --category psychology --format short
    python -m scripts.run_pipeline --category history --format long
    python -m scripts.run_pipeline --resume <run_id>
"""

from __future__ import annotations

import argparse

from core.database.session import init_db
from core.logging_setup import get_logger
from core.orchestrator import Orchestrator

log = get_logger("scripts.run_pipeline")


# Long edge of the frame for each quality tier.
_RES_TIERS = {"1080": 1920, "1440": 2560, "4k": 3840}


def _apply_output_format(args) -> None:
    """Override the configured frame size from --orientation / --resolution.

    Vertical (9:16) is for Shorts/TikTok/Reels; landscape (16:9) is for normal
    YouTube videos. Shorts default to vertical and long-form to landscape, which
    is why a `--format short` render looks like a narrow strip on a monitor.
    """
    from core.config import get_settings

    s = get_settings()
    fmt = s.formats.short if args.video_format == "short" else s.formats.long
    orientation = args.orientation or ("vertical" if args.video_format == "short" else "landscape")

    long_edge = _RES_TIERS.get(args.resolution or "", None)
    if long_edge is None:
        # Keep the configured size, just honour the requested orientation.
        long_edge = max(fmt.resolution)
    short_edge = int(round(long_edge * 9 / 16))

    fmt.resolution = ([short_edge, long_edge] if orientation == "vertical"
                      else [long_edge, short_edge])
    log.info("Output: %s %dx%d @%dfps", orientation, fmt.resolution[0],
             fmt.resolution[1], fmt.fps)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one Mind_Vault production run")
    parser.add_argument("--category", choices=["psychology", "history"], default=None,
                        help="content category (default: CEO chooses to balance the mix)")
    parser.add_argument("--format", dest="video_format", choices=["short", "long"], default="short")
    parser.add_argument("--resume", metavar="RUN_ID", default=None, help="resume a checkpointed run")
    parser.add_argument("--orientation", choices=["vertical", "landscape"], default=None,
                        help="vertical = Shorts/TikTok/Reels (9:16); landscape = normal "
                             "YouTube (16:9). Default: vertical for short, landscape for long.")
    parser.add_argument("--resolution", choices=["1080", "1440", "4k"], default=None,
                        help="output height for landscape (or width for vertical). "
                             "1440/4k look sharper on YouTube but render slower.")
    args = parser.parse_args()

    _apply_output_format(args)

    init_db()  # ensure tables exist
    orch = Orchestrator()

    ctx = orch.resume(args.resume) if args.resume else orch.produce(
        category=args.category, video_format=args.video_format)

    print("\n" + "=" * 64)
    print(f"RUN {ctx.run_id}  |  {ctx.category}  |  {ctx.video_format}")
    print("=" * 64)
    print(f"Topic     : {ctx.topic.angle if ctx.topic else '-'}")
    print(f"Hook      : {ctx.selected_hook.text if ctx.selected_hook else '-'}")
    if ctx.script:
        print(f"Title     : {ctx.script.title}  ({ctx.script.word_count} words)")
    if ctx.quality:
        print(f"Quality   : {ctx.quality.overall_score}  passed={ctx.quality.passed}")
    if ctx.voice:
        print(f"Narration : {ctx.voice.audio_path}  ({ctx.voice.duration}s, {ctx.voice.provider})")
    if ctx.video:
        print(f"Video     : {ctx.video.video_path}  (engine={ctx.video.engine})")
    if ctx.publish_results:
        for r in ctx.publish_results:
            print(f"Publish   : {r.platform:<10} {r.status}  {r.note}")
    if ctx.extra.get("failed_stage"):
        print(f"FAILED at : {ctx.extra['failed_stage']} -> {ctx.extra.get('error')}")
        print(f"Resume    : python -m scripts.run_pipeline --resume {ctx.run_id}")
    print("=" * 64 + "\n")


if __name__ == "__main__":
    main()
