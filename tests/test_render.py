"""Parallel scene rendering: same output as serial, settings reach the workers."""

import pytest

from core.config import get_settings
from core.media import video
from core.schemas import Scene


def _jobs(tmp_path):
    ffmpeg = video._ffmpeg_exe()
    if not ffmpeg:
        pytest.skip("ffmpeg not available")
    tmp_path.mkdir(parents=True, exist_ok=True)
    kinds = ["title", "stat", "quote", "bullets"]
    return [(i, Scene(index=i, narration=f"Beat {i}: 42% of people", visual_prompt="x",
                      duration=0.8, text_overlay=f"Beat {i}", animation_kind=k),
             tmp_path / f"p{i:04d}.mp4", [320, 180], 10, "Mind_Vault", ffmpeg)
            for i, k in enumerate(kinds)]


def test_parallel_render_matches_serial_in_order(tmp_path):
    s = get_settings()
    s.video.render_workers = 1
    serial = video._render_parts(_jobs(tmp_path / "serial"))
    s.video.render_workers = 3
    jobs = _jobs(tmp_path / "parallel")
    parallel = video._render_parts(jobs)
    assert parallel == serial == ["anim"] * 4
    assert all(j[2].stat().st_size > 0 for j in jobs)


def test_worker_receives_parent_settings():
    s = get_settings()
    dump = s.model_dump()
    dump["video"]["crf"] = 31
    dump["brand"]["name"] = "Worker Copy"
    video._init_worker(dump)          # what each worker runs on start-up
    assert get_settings().video.crf == 31
    assert get_settings().brand.name == "Worker Copy"


def test_worker_count_respects_config_and_job_count():
    s = get_settings()
    s.video.render_workers = 4
    assert video._render_workers(2) == 2
    assert video._render_workers(10) == 4
    s.video.render_workers = 0
    assert video._render_workers(1) == 1
