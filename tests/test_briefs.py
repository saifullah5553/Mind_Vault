"""Picture briefs: one detailed master prompt per line (core/media/briefs.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.media import briefs

PAVLOV = {"cue": "Everyone knows the story", "kind": "photo",
          "who": "Ivan Petrovich Pavlov (1849-1936), Russian physiologist",
          "setting": "his laboratory with a dog", "clothing": "white laboratory coat",
          "mood": "serious, focused", "era": "1890-1936",
          "search": ["Pavlov laboratory Wellcome"], "must": ["Pavlov"],
          "any": ["Ivan", "I. P.", "laboratory"], "reject": ["statue", "monument"]}


def _hit(title, about="", width=3000):
    return {"title": title, "about": about, "width": width, "license": "CC BY 4.0",
            "url": f"https://upload.wikimedia.org/x/thumb/a/ab/{title}/3840px-{title}"}


def _write(tmp_path, items) -> Path:
    import yaml
    p = tmp_path / "film.pictures.yaml"
    p.write_text(yaml.safe_dump(items, allow_unicode=True), encoding="utf-8")
    return p


def test_load_reads_every_field(tmp_path):
    b = briefs.load(_write(tmp_path, [{**PAVLOV, "not": "Valentin Pavlov"}]))[0]
    assert b.cue == "Everyone knows the story" and b.kind == "photo"
    assert b.avoid == "Valentin Pavlov" and b.must == ["Pavlov"] and b.years() == (1890, 1936)


def test_load_skips_entries_without_a_cue_and_fixes_unknown_kinds(tmp_path):
    out = briefs.load(_write(tmp_path, [{"kind": "photo"}, {"cue": "x", "kind": "video"}]))
    assert len(out) == 1 and out[0].kind == "hold"


def test_pictures_file_sits_beside_the_script():
    assert briefs.pictures_file("content/scripts/pavlov.txt").name == "pavlov.pictures.yaml"


def test_each_brief_takes_the_first_free_line_with_its_cue():
    bs = [briefs.Brief(cue="the bell"), briefs.Brief(cue="the bell")]
    got = briefs.match(bs, ["no", "Then the bell rang.", "And the bell stuck."])
    assert sorted(got) == [1, 2]


@pytest.mark.parametrize("title,about,ok", [
    ("Pavlov experiments with dog Wellcome M0014738.jpg", "Ivan Pavlov laboratory", True),
    ("Chairman Vladimir Pavlov.jpg", "", False),                  # no Ivan / I. P. / laboratory
    ("Laboratory dogs 1904.jpg", "", False),                       # no Pavlov
    ("Monument to Ivan Pavlov, Ryazan.jpg", "", False),            # rejected word
    ("The Soviet Union 1991 stamp of Ivan Pavlov.jpg", "", False), # always rejected + wrong years
    ("Ivan Pavlov laboratory 2017.jpg", "", False),                # outside the brief's years
])
def test_check_applies_the_brief(title, about, ok):
    b = briefs.load_one(PAVLOV) if hasattr(briefs, "load_one") else briefs.Brief(
        **{k: v for k, v in PAVLOV.items()})
    assert (briefs.check(b, _hit(title, about)) == "") is ok


def test_score_prefers_the_described_setting():
    b = briefs.Brief(**PAVLOV)
    lab = _hit("I.P. Pavlov in his laboratory with a dog.jpg", "white coat")
    desk = _hit("I.P. Pavlov portrait.jpg")
    assert briefs.score(b, lab) > briefs.score(b, desk)


def test_candidates_are_cached_and_filtered(monkeypatch):
    from core.media import stock
    calls = []

    def commons(q, limit=3, curated=None):
        calls.append(q)
        return [_hit("Pavlov experiments with dog Wellcome M0014738.jpg", "Ivan Pavlov laboratory"),
                _hit("GRAIL spacecraft.jpg")]
    monkeypatch.setattr(stock, "_commons_search", commons)
    monkeypatch.setattr(stock, "_openverse_search", lambda q, limit=3: [])
    b = briefs.Brief(**PAVLOV)
    first = briefs.candidates(b)
    again = briefs.candidates(b)
    assert [h["title"] for h in first] == ["Pavlov experiments with dog Wellcome M0014738.jpg"]
    assert again == first and calls == ["Pavlov laboratory Wellcome"]   # second plan: no search


def test_chosen_uses_the_pick_then_the_best_and_none_falls_back():
    found = [_hit("A.jpg"), _hit("B.jpg")]
    assert briefs.chosen(briefs.Brief(cue="x", pick="B.jpg"), found)["title"] == "B.jpg"
    assert briefs.chosen(briefs.Brief(cue="x", pick="File:b.jpg"), found)["title"] == "B.jpg"
    assert briefs.chosen(briefs.Brief(cue="x"), found)["title"] == "A.jpg"
    assert briefs.chosen(briefs.Brief(cue="x", pick="none"), found) is None
    assert briefs.chosen(briefs.Brief(cue="x"), []) is None


def test_thumb_url_asks_for_a_small_copy():
    assert "/330px-" in briefs.thumb_url(_hit("A.jpg"))


def _scenes(texts):
    from core.schemas import Scene
    return [Scene(index=i, narration=t, visual_prompt=t, duration=3.0) for i, t in enumerate(texts)]


def test_unbriefed_lines_hold_the_previous_shot_never_a_random_picture(tmp_path, monkeypatch):
    """With briefs there is no TOPIC pool: a line without a usable picture keeps
    the previous shot."""
    from PIL import Image

    from core.config import get_settings
    from core.media import images, stock

    s = get_settings()
    s.images.provider = "stock"
    s.images.width, s.images.height = 320, 180

    def fake_download(url, dest):
        Image.new("RGB", (640, 400), (120, 90, 60)).save(dest)
        return True
    monkeypatch.setattr(stock, "_download", fake_download)
    monkeypatch.setattr(stock, "_commons_search", lambda q, limit=3, curated=None: [
        _hit("Pavlov experiments with dog Wellcome M0014738.jpg", "Ivan Pavlov laboratory")])
    monkeypatch.setattr(stock, "_openverse_search", lambda q, limit=3: [])
    monkeypatch.setattr(stock, "fetch_pool", lambda *a, **k: pytest.fail("no pool with briefs"))
    pics = _write(tmp_path, [PAVLOV, {"cue": "Where did", "kind": "hold"}])
    scenes = _scenes(["Everyone knows the story of Pavlov's dogs.", "Where did the bell come from?",
                      "Nothing was briefed here."])
    images.generate_images(scenes, tmp_path / "run", topic="Ivan Pavlov", category="history",
                           subtitles=False, pictures=str(pics))
    assert scenes[0].source.startswith("brief 'Everyone knows the story'")
    assert scenes[1].source.startswith("hold") and scenes[2].source.startswith("hold")
    assert Path(scenes[1].image_path).read_bytes() == Path(scenes[0].image_path).read_bytes()
