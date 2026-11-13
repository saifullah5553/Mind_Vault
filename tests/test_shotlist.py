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


def test_reels_open_on_their_own_feet():
    from core.media.reels import opening_cost
    assert opening_cost("It was only the start.") > 0
    assert opening_cost("In 1866, those two domains joined forces.") > 0
    assert opening_cost("The Dutch.") > 0
    assert opening_cost("In 1858, the American consul Townsend Harris won a far bigger deal.") < 0
    assert opening_cost("Tokugawa Yoshinobu offered to give up his power.") < 0


def test_namesakes_lose_to_the_real_person():
    from core.media.stock import relevance
    line = "The first man to make real progress was Thomas Young, an English doctor."
    assert relevance(line, {"title": "Portrait of Thomas Young.jpg"})[0] > 0
    assert relevance(line, {"title": "Walter Thomas [young man bow"})[0] < 0
    assert relevance(line, {"title": "A Young Art Student (Portrait of Thomas Eakins).jpg"})[0] < 0
    # not a person picture: left for the reviewer, not penalised
    assert relevance("Captured in Egypt by the British Army in 1801.",
                     {"title": "The Rosetta Stone (Left Side) - British Museum.jpg"})[0] > 0
