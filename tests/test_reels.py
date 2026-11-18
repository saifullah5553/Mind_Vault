"""Numbered reels cut from a long video."""
from datetime import datetime, timezone

import pytest

from core.media import reels


def _srt(sentences: list[tuple[float, float, str]]) -> str:
    rows = []
    for n, (a, b, text) in enumerate(sentences, 1):
        rows.append(f"{n}\n{reels._stamp(a)} --> {reels._stamp(b)}\n{text}\n")
    return "\n".join(rows)


def _story(seconds: float, each: float = 6.0, gap: float = 0.3):
    out, t, i = [], 0.0, 0
    while t + each <= seconds:
        out.append((t, t + each, f"Sentence number {i} happened."))
        t += each + gap
        i += 1
    out.append((t, t + 4, "Join Mind Vault for more stories about the human mind and history."))
    return out


def test_sentences_join_cues_and_drop_the_cta():
    srt = _srt([(0, 1.2, "On the night of the"), (1.2, 2.7, "thirty-first of January,"),
                (3.3, 6.0, "1953, a storm came."), (6.5, 8, "Join Mind Vault for more stories.")])
    s = reels.sentences(reels.parse_srt(srt), "Join Mind Vault for more stories about the human mind.")
    assert len(s) == 1 and s[0].text.startswith("On the night") and s[0].end == 6.0
    assert len(s[0].cues) == 3


def test_part_count_stays_between_five_and_ten():
    assert reels.part_count(300) == 5
    assert reels.part_count(438) == 6
    assert reels.part_count(600) == 9
    assert reels.part_count(2000) == 10


def test_split_covers_the_story_in_order_at_sentence_breaks():
    sents = reels.sentences(reels.parse_srt(_srt(_story(438))), "Join Mind Vault for more stories")
    parts = reels.split(sents)
    assert [p.number for p in parts] == list(range(1, 7)) and all(p.total == 6 for p in parts)
    assert parts[0].start == 0.0
    used = [s for p in parts for s in p.sentences]
    assert used == sents                                  # nothing lost, nothing repeated
    assert all(30 <= p.duration <= 110 for p in parts)
    assert all(a.end <= b.start for a, b in zip(parts, parts[1:]))
    assert "Join Mind Vault" not in parts[-1].text


def test_split_prefers_a_paragraph_pause():
    story = [(i * 6.3, i * 6.3 + 6, f"S{i}.") for i in range(60)]
    # A long pause after sentence 29 (a paragraph break) should become a cut.
    story = [(a + (2.0 if i >= 30 else 0), b + (2.0 if i >= 30 else 0), t)
             for i, (a, b, t) in enumerate(story)]
    parts = reels.split(reels.sentences(reels.parse_srt(_srt(story))), parts=6)
    assert any(p.sentences[0].text == "S30." for p in parts)


def test_part_captions_start_at_zero():
    sents = reels.sentences(reels.parse_srt(_srt(_story(438))))
    p = reels.split(sents)[2]
    first = reels.parse_srt(reels.part_srt(p))
    assert 0 <= first[0].start < 0.5 and first[-1].end <= p.duration + 1e-6


def test_titles_file_and_youtube_titles():
    rows = reels.read_titles("# notes\nTHE NIGHT THE SEA CAME | The 1953 Flood Night\n"
                             "A COUNTRY ANSWERS | How the Delta Works Began (Part 2/2)\n", 2)
    assert rows[0] == ("THE NIGHT THE SEA CAME", "The 1953 Flood Night")
    assert reels.youtube_title(rows[1][1], 2, 2) == "How the Delta Works Began (Part 2/2)"
    assert len(reels.youtube_title("x" * 150, 1, 6)) <= 100
    with pytest.raises(ValueError):
        reels.read_titles("ONE | One\n", 2)
    with pytest.raises(ValueError):
        reels.read_titles("NO TITLE\n", 1)


def test_reel_slots_follow_the_long_video_and_skip_taken():
    from scripts.make_reels import next_reel_slots
    # Long video out Mon 9 Nov 2026 14:00 New York (19:00 UTC); reels from 15:00 on.
    after = datetime(2026, 11, 9, 20, 0, tzinfo=timezone.utc)
    taken = [datetime(2026, 11, 9, 21, 0, tzinfo=timezone.utc).isoformat()]   # 16:00 NY
    slots = next_reel_slots(after, 4, taken, "America/New_York")
    ny = [s.astimezone(__import__("zoneinfo").ZoneInfo("America/New_York")).strftime("%a %H:%M")
          for s in slots]
    assert ny == ["Mon 18:00", "Mon 20:00", "Mon 22:00", "Tue 07:00"]


def test_every_part_ends_by_asking_the_viewer_to_act():
    assert reels.next_step(1, 5) == "LIKE & SUBSCRIBE FOR PART 2/5"
    assert reels.next_step(4, 5) == "LIKE & SUBSCRIBE FOR PART 5/5"
    assert reels.next_step(5, 5).startswith("LIKE, SHARE & SUBSCRIBE") and "FULL VIDEO" in reels.next_step(5, 5)


def test_closing_ask_is_cut_from_reels_old_and_new_wording():
    from core.config import get_settings
    for cta in (get_settings().brand.cta, "Join Mind Vault for more stories about the human mind and history."):
        srt = _srt([(0, 3, "In 1953, a storm came."), (3.3, 6.0, "The dikes broke."), (6.5, 9, cta)])
        s = reels.sentences(reels.parse_srt(srt), get_settings().brand.cta)
        assert [x.text for x in s] == ["In 1953, a storm came.", "The dikes broke."]
    assert "subscribe" in get_settings().brand.cta and "share" in get_settings().brand.cta


def test_old_closing_asks_are_still_cut_from_reels():
    from core.config import get_settings
    for old in ("If you enjoyed this story, like, subscribe and share it, to stay updated.",
                "Join Mind Vault for more stories."):
        srt = _srt([(0, 3, "In 1953, a storm came."), (3.3, 6.0, "The dikes broke."), (6.5, 9, old)])
        s = reels.sentences(reels.parse_srt(srt), get_settings().brand.cta)
        assert [x.text for x in s] == ["In 1953, a storm came.", "The dikes broke."]


def _greeted():
    return _srt([(0.0, 4.0, "In 1904, a man won the Nobel Prize."),
                 (4.5, 8.0, "Hello, friends, and welcome to your own channel, Mind Vault."),
                 (8.3, 10.0, "Today's story: the truth behind Pavlov's dogs."),
                 (10.6, 14.0, "Everyone knows the story."),
                 (14.3, 18.0, "Almost none of it is true.")])


def test_reels_cut_the_greeting_and_keep_the_hook():
    s = reels.sentences(reels.parse_srt(_greeted()))
    assert [x.text for x in s] == ["In 1904, a man won the Nobel Prize.",
                                   "Everyone knows the story.", "Almost none of it is true."]
    assert s[1].skip == (4.45, 10.5) and s[0].skip is None and s[2].skip is None
    assert reels.is_greeting("Hello friends, and welcome back") and not reels.is_greeting("Hello.")


def test_a_part_across_the_greeting_is_shorter_and_its_captions_close_the_gap():
    s = reels.sentences(reels.parse_srt(_greeted()))
    part = reels.Part(1, 1, 0.0, 18.2, s)
    assert part.cuts == [(4.45, 10.5)]
    assert part.duration == pytest.approx(18.2 - 6.05)
    srt = reels.part_srt(part)
    assert "00:00:04,550 --> 00:00:07,950" in srt      # 'Everyone knows' right after the hook
    assert "Hello" not in srt and "Today" not in srt


def test_a_part_starting_after_the_greeting_has_nothing_to_cut():
    s = reels.sentences(reels.parse_srt(_greeted()))
    assert reels.Part(2, 2, 10.48, 18.2, s[1:]).cuts == []


def test_the_new_closing_ask_and_greeting():
    from core.config import get_settings
    b = get_settings().brand
    assert b.cta.startswith("If you're enjoying our videos, subscribe to Mind Vault")
    assert "like and share" in b.cta
    assert b.greeting.startswith("Hello, friends, and welcome to your own channel, Mind Vault.")
    assert "{topic}" in b.greeting and reels.is_greeting(b.greeting.replace("{topic}", "x"))
