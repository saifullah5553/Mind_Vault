"""The shot list's risk flags (core/media/shotlist.py), from faults found by hand."""
from core.media.shotlist import build, risks

HARRIS = "It was only the start. In 1858, the American consul Townsend Harris won a far bigger deal."


def test_namesakes_are_flagged():
    assert any("namesake" in r for r in risks(HARRIS, "Dr. Francis Townsend & Rep. A.J. Elliott.jpg"))
    assert any("namesake" in r for r in risks(HARRIS, "Harris Hall 1589 Amst Av jeh.jpg"))
    assert any("namesake" in r for r in risks("It was built by British engineers, led by Edmund Morel.",
                                              "E.D Morel, ca. 1900-1915.jpg"))


def test_credit_only_and_modern_and_unrelated():
    assert risks("The Harris Treaty opened Kanagawa and four other ports.",
                 "Air shot, Cape May Coast Guard Station Airport by Harris & Ewing, photographer") == \
        ["matches only the photographer's credit"]
    assert "modern photo over a past event" in risks(
        "Within a year, those were merged into seventy-two prefectures.",
        "February 2024, buildings in Yokohama 10.jpg")
    assert risks("Five young girls had sailed with them.",
                 "American tourist party arriving at Tokyo") == ["shares no word with the line"]


def test_good_pictures_pass():
    perry = "Their commander, Commodore Matthew Perry, carried a letter from President Millard Fillmore."
    assert risks(perry, "Commodore-Perry-Visit-Kanagawa-1854.jpg") == []
    assert risks("In 1853, Japan watched four foreign warships sail into its bay.",
                 "Ca. 1853 Kawaraban - Commodore Perry's Arrival in Edo Bay.jpg") == []
    assert risks("Today, the Tomioka Silk Mill is a UNESCO World Heritage Site.",
                 "Warehouse, Tomioka Silk Mill, Gunma (2015-05-06).jpg") == []


def test_build_marks_lines():
    scenes = [{"index": 0, "narration": "Title.", "duration": 3, "animation_kind": "title"},
              {"index": 1, "narration": HARRIS, "duration": 4, "source": "Harris Hall 1589 Amst Av.jpg"},
              {"index": 2, "narration": "Perry sailed home.", "duration": 4,
               "source": "Commodore Perry portrait"}]
    text, flagged = build(scenes)
    assert flagged == 1 and "!! namesake" in text and "CARD title" in text
