"""Scene types chosen from what each line says (core/media/scenes.py)."""
import json

from core.media import scenes


def test_object_showcase_needs_the_picture_to_show_it():
    line = "Thorgeir pulled a fur cloak over his head."
    spec = scenes.showcase_for(line, {"title": "Viking fur cloak replica"})
    assert spec == {"style": "object", "label": "FUR CLOAK", "sub": ""}
    assert scenes.showcase_for(line, {"title": "Lake at dusk"}) is None


def test_document_showcase_prefers_the_items_name():
    line = "The poems survive in a single manuscript, the Codex Regius, written around 1270."
    spec = scenes.showcase_for(line, {"title": "Codex Regius (019).JPG"})
    assert spec["style"] == "document"
    assert spec["label"] == "CODEX REGIUS" and spec["sub"] == "1270"


def test_layers_only_for_digging_and_dating():
    assert scenes.layers_for("Carbon dating of the buried layers pointed to 580 BCE.") == \
        {"label": "580 BCE", "sub": "DATING THE LAYERS"}
    assert scenes.layers_for("Archaeologists began to excavate in 2014.")["sub"] == "EXCAVATION"
    assert scenes.layers_for("The ground beneath Thingvellir is splitting.") is None


def test_dates():
    assert scenes.date_in("In 874 he arrived.") == "874"
    assert scenes.date_in("about 580 BCE") == "580 BCE"
    assert scenes.date_in("in the thirteenth century") == "THIRTEENTH CENTURY"
    assert scenes.date_in("There were 200 people.") == ""


def test_scenes_draw(tmp_path):
    from PIL import Image

    from core.media.animation import Style, render_animated_segment
    photo = tmp_path / "pot.jpg"
    Image.new("RGB", (800, 600), (150, 90, 60)).save(photo)
    res = (320, 180)
    for kind in ("showcase:" + json.dumps({"style": "object", "label": "CLAY POT", "sub": "580 BCE",
                                          "photo": str(photo)}),
                 "layers:" + json.dumps({"label": "580 BCE", "sub": "EXCAVATION"})):
        out = tmp_path / f"{kind[:4]}.mp4"
        assert render_animated_segment("x", kind, out, res, 10, 1.0)
        assert out.stat().st_size > 1000
    frame = Image.new("RGB", res)
    scenes.draw_lower_third(frame, "THINGVELLIR", "ICELAND", res, 2.0, 5.0)
    assert frame.getbbox() is not None
    assert scenes.describe("layers:" + json.dumps({"label": "580 BCE"})) == "LAYERS 580 BCE"


def test_director_labels_and_showcases(tmp_path):
    from PIL import Image

    from core.media.images import _direct
    from core.schemas import Scene
    photo = tmp_path / "p.jpg"
    Image.new("RGB", (100, 100)).save(photo)
    state = {"showcases": [], "labelled": set(), "labels": []}
    a = Scene(index=4, narration="In the grave lay a Viking sword.", visual_prompt="", duration=3)
    _direct(a, {"title": "Viking sword, Derby Museum", "path": str(photo)}, tmp_path, state)
    assert a.animation_kind.startswith("showcase:")
    b = Scene(index=9, narration="They rode to Thingvellir every summer.", visual_prompt="", duration=3)
    _direct(b, {"title": "Thingvellir National Park", "path": str(photo)}, tmp_path, state)
    assert b.label == "THINGVELLIR" and not b.animation_kind
    c = Scene(index=14, narration="Again at Thingvellir.", visual_prompt="", duration=3)
    _direct(c, {"title": "Thingvellir lake", "path": str(photo)}, tmp_path, state)
    assert c.label == ""                       # captioned once


def test_plurals_and_durations():
    spec = scenes.showcase_for("Their women fastened their dresses with oval brooches of bronze.",
                               {"title": "Austris brooch (HST DIG56330).jpg"})
    assert spec["label"] == "OVAL BROOCHES"
    assert scenes.date_in("dug up the remains, around 1000 years later.") == ""
    assert scenes.date_in("around 1000 CE") == "1000 CE"


def test_captions_come_from_the_photo_title_only(tmp_path):
    from PIL import Image

    from core.media.images import _direct
    from core.schemas import Scene
    photo = tmp_path / "p.jpg"
    Image.new("RGB", (100, 100)).save(photo)
    state = {"showcases": [], "labelled": set(), "labels": []}
    a = Scene(index=0, narration="So the farmers travelled to Thingvellir.", visual_prompt="", duration=3)
    _direct(a, {"title": "Althingi.jpg", "about": "Parliament, not at Thingvellir",
                "path": str(photo)}, tmp_path, state)
    assert a.label == ""                    # the description is not proof of the place
    b = Scene(index=5, narration="Not in the valley but in Reykjavík, near Ingólfur's bay.",
              visual_prompt="", duration=3)
    _direct(b, {"title": "Reykjavik Standbeeld van Ingolfur Arnarsson", "path": str(photo)},
            tmp_path, state)
    assert b.label == "REYKJAVÍK"           # one name, no possessive


def test_caption_carries_the_whole_name(tmp_path):
    from PIL import Image

    from core.media.images import _direct
    from core.schemas import Scene
    photo = tmp_path / "p.jpg"
    Image.new("RGB", (100, 100)).save(photo)
    state = {"showcases": [], "labelled": set(), "labels": []}
    s = Scene(index=0, narration="The first man to make real progress was Thomas Young, an English doctor.",
              visual_prompt="", duration=3)
    _direct(s, {"title": "Portrait of Thomas Young.jpg", "path": str(photo)}, tmp_path, state)
    assert s.label == "THOMAS YOUNG"
