"""Animated maps for lines that name a place or a country."""
import json

import pytest

from core.media import maps

pytestmark = pytest.mark.skipif(
    not all((maps.DATA_DIR / n).exists() for n in maps._FILES),
    reason="Natural Earth data not downloaded (storage/data/naturalearth)")

STORY = [
    "On the night of the thirty-first of January, 1953, a storm hit the Netherlands.",
    "Most of them lived in the low islands of Zeeland, in the south-west of the country.",
    "For a nation that had fought the sea for a thousand years, it was a defeat.",
    "In the early sixteen hundreds, a lake north of Amsterdam called the Beemster was drained.",
    "It became a model of Dutch land reclamation.",
    "Further south, at Kinderdijk, a row of windmills was built.",
    "They still stand along the water.",
    "In 1916, a storm flood hit the coast around the Zuiderzee.",
    "Behind it, the salt sea slowly turned into a freshwater lake, the IJsselmeer.",
    "Rotterdam is one of the busiest ports in the world.",
    "So in 1997, the Dutch finished the Maeslant barrier.",
]


def test_maps_go_to_first_mentions_spread_and_never_the_opening():
    plan = maps.plan_maps(STORY, limit=4, spacing=2)
    assert 0 not in plan and 1 <= len(plan) <= 4
    names = [s["place"] for s in plan.values()]
    assert names[0] == "Zeeland"
    assert all(s["country"] == "Netherlands" for s in plan.values())
    idx = sorted(plan)
    assert all(b - a >= 2 for a, b in zip(idx, idx[1:]))


def test_the_landmark_beats_the_city_it_is_measured_from():
    plan = maps.plan_maps(STORY, limit=10, spacing=1)
    assert plan[3]["place"] == "Beemster"
    # The IJsselmeer is the old Zuiderzee: no second pin on the same spot.
    assert 8 not in plan


def test_unknown_or_ambiguous_names_make_no_map():
    assert maps.plan_maps(["Intro.", "Jordan walked home.", "Victoria smiled."]) == {}
    # A city outside the story's countries is not guessed.
    assert maps.plan_maps(["Intro.", "Japan opened its ports.", "He moved to Paris."],
                          limit=4, spacing=1) == {1: {"place": "", "country": "Japan"}}


def test_a_map_scene_renders(tmp_path):
    from core.media.animation import render_animated_segment
    spec = {"place": "Rotterdam", "lon": 4.48, "lat": 51.92, "country": "Netherlands"}
    out = tmp_path / "m.mp4"
    assert render_animated_segment("Rotterdam is a port.", "map:" + json.dumps(spec), out,
                                   (320, 180), 10, 1.0)
    assert out.stat().st_size > 1000
