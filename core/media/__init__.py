"""Pluggable, free-first media layer: text-to-speech, images, video assembly."""

from core.media.images import generate_images
from core.media.tts import synthesize_speech
from core.media.video import assemble_video

__all__ = ["generate_images", "synthesize_speech", "assemble_video"]
