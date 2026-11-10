"""Each line gets the picture that fits what it says (stock.assign_pictures)."""

from core.media.stock import assign_pictures, match_words, relevance


def _pic(title, part=0, about="", query=""):
    return {"title": title, "part": part, "about": about, "query": query, "path": title}


def test_accents_and_plurals_fold():
    assert "thingvellir" in match_words("Þingvellir National Park")
    assert "dike" in match_words("the dikes broke")
    assert match_words("Almannagjá") == match_words("Almannagja")


def test_named_place_beats_search_order():
    pool = [_pic("Snowy street in Reykjavik"), _pic("Almannagja gorge at Thingvellir")]
    out = assign_pictures(["They rode to Almannagja, a gorge in the rock."], [0], pool, [True])
    assert out[0]["title"].startswith("Almannagja")


def test_description_counts_when_title_is_a_code():
    pool = [_pic("DSC_0042"), _pic("IMG_7781", about="Turf houses at Glaumbaer farm")]
    out = assign_pictures(["Families lived in turf houses."], [0], pool, [True])
    assert out[0]["title"] == "IMG_7781"
    assert relevance("Families lived in turf houses.", pool[1])[0] > 0


def test_no_repeats_and_hidden_lines_dont_use_pictures():
    pool = [_pic("a lava field"), _pic("a waterfall"), _pic("a fjord")]
    lines = ["The lava field.", "Footage line.", "The waterfall.", "The fjord."]
    out = assign_pictures(lines, [0] * 4, pool, [True, False, True, True])
    shown = [out[i]["title"] for i in (0, 2, 3)]
    assert len(set(shown)) == 3
    assert out[1] is not None


def test_spent_part_borrows_from_nearest_part():
    pool = [_pic("settlers ship", 0), _pic("assembly crowd", 1), _pic("republic flag", 3)]
    out = assign_pictures(["One.", "Two.", "Three."], [1, 1, 1], pool, [True, True, True])
    assert out[0]["part"] == 1
    assert out[1]["part"] == 0          # |0-1| = 1 beats |3-1| = 2
    assert out[2]["part"] == 3


def test_other_part_only_when_line_names_it():
    pool = [_pic("farm field", 0), _pic("Law Rock Logberg Thingvellir", 1)]
    named = assign_pictures(["Then the speaker climbed the Law Rock at Thingvellir."], [0],
                            pool, [True])
    assert named[0]["title"].startswith("Law Rock")
    plain = assign_pictures(["the rock and the law of the land"], [0], pool, [True])
    assert plain[0]["title"] == "farm field"


def test_search_label_links_foreign_names_to_the_line():
    pool = [_pic("Waterfall in autumn"),
            _pic("Thingvellir-63a-Logberg-2018", query="Logberg Thingvellir")]
    pool[1]["label"] = "Law Rock lawspeaker"
    out = assign_pictures(["At the heart of it all stood the Law Rock."], [0], pool, [True])
    assert out[0]["title"].startswith("Thingvellir")


def test_longer_form_of_a_name_matches():
    assert relevance("They called it the Althing.", _pic("Althingi building"))[0] > 0


def test_picture_of_an_unnamed_person_comes_last():
    pool = [_pic("King Inge with young Hakon"), _pic("Lake at dusk")]
    out = assign_pictures(["So they turned to a chieftain named Thorgeir."], [0], pool, [True])
    assert out[0]["title"] == "Lake at dusk"
    named = assign_pictures(["King Inge ruled Norway."], [0], pool, [True])
    assert named[0]["title"].startswith("King Inge")


def test_spent_part_prefers_a_fitting_picture_over_the_nearest():
    pool = [_pic("settlers ship", 0), _pic("farm in snow", 1), _pic("turf house booth", 3)]
    out = assign_pictures(["First line.", "They camped in booths of turf."], [1, 1], pool,
                          [True, True])
    assert out[1]["title"] == "turf house booth"


def test_line_matching_two_parts_moves_to_the_nearest_ahead():
    from core.media.stock import part_per_line
    topic = "a @ settler|Families; b @ assembly; c @ Norway"
    lines = ["The settler came.", "Most families sailed from Norway.", "Then the assembly.",
             "The king of Norway."]
    assert part_per_line(lines, topic) == [0, 0, 1, 2]


def test_numbered_series_is_one_picture():
    from core.media.stock import _series_key
    assert _series_key("Thingvellir-63a-Lögberg-2018-gje.jpg") == \
        _series_key("Thingvellir-63c-Lögberg-2018-gje.jpg")
    assert _series_key("Almannagja gorge") != _series_key("Law Rock at dusk")


def test_dark_picture_is_rejected(tmp_path):
    from PIL import Image

    from core.media.stock import _too_dark
    Image.new("RGB", (64, 36), (12, 12, 14)).save(tmp_path / "dark.jpg")
    img = Image.new("RGB", (64, 36), (40, 90, 140))
    for x in range(0, 64, 4):
        for y in range(36):
            img.putpixel((x, y), (230, 220, 200))
    img.save(tmp_path / "ok.jpg")
    assert _too_dark(tmp_path / "dark.jpg")
    assert not _too_dark(tmp_path / "ok.jpg")
