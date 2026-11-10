---
name: mind-vault-production
description: Write, review and improve Mind_Vault documentaries (psychology, human history, the history of countries). Use when writing a documentary script and its sources file, reviewing a rendered video or reel as script writer/chief editor/producer/director/social media/SEO expert, critiquing a contact sheet, or choosing a title, thumbnail text and tags.
---

# Mind_Vault production

The commands and the publishing steps are in `docs/DAILY_REVIEW.md`. This skill covers
the craft: how to write the script, and how to judge the result.

## 1. Choosing the topic

- Rotate the categories: psychology about a third of the time, and human history or a
  country's history the rest. Never repeat a topic. Check titles in
  `storage/review/*/review.json` and `content/scripts/*.txt` first.
- Countries: tell how the nation came to be, for example its founding, a turning point or
  a remarkable era. Be respectful, and take no side in current political, religious,
  ethnic or border disputes. Leave out the history of active conflicts entirely.
- Pick a story with a person, a place and a moment, not a list. "In 1853, four black
  ships sailed into Edo Bay" beats "Japanese history overview".
- Every claim must be something you can check on a reliable page: Britannica, a
  university, a museum, a national archive, or the original study. If you can't find a
  source, the claim doesn't go in.

## 2. The script file

Save it as `content/scripts/<slug>.txt`:

```
TOPIC: the history of Japan            <- what footage and photos are searched for (short, concrete)
SUBCATEGORY: Japan
TITLE: How Japan Opened to the World in 15 Years
DESCRIPTION: Two sentences: what happens, and why it matters. Include the main keyword.
THUMBNAIL: JAPAN'S 15-YEAR LEAP        <- 2 to 4 words, capitals
TAGS: history of japan, meiji restoration, black ships, commodore perry, edo period, japan documentary, ...

[INTRODUCTION]
The hook, then the promise of the story.

[CHAPTER: The Black Ships]              <- chapters shape the writing; they are never spoken or shown
...

[CONCLUSION]
...

[CTA]
Join Mind Vault for more stories about the human mind and history.
```

Save the sources next to it as `content/scripts/<slug>.sources.txt`, one checked fact per
line, at least 8:

```
Commodore Matthew Perry's ships arrived at Uraga, near Edo, in July 1853 | https://www.britannica.com/...
```

Then render it:

```bash
.venv\Scripts\python -m scripts.run_pipeline --new-from-script content/scripts/<slug>.txt --category history --format long
```

Use `--category psychology` for psychology topics.

## 3. Writing for the ear

- **Length: 1,050–1,250 spoken words.** That's about 8–9 minutes. The limit is 10 minutes,
  including the end card.
- **The hook is the first sentence, and the strongest moment in the story.** Give a fact
  and a tension: a date, a person, and something surprising. Never "In this video" or
  "Have you ever wondered". The video opens on whatever the hook names, so name
  something filmable.
- In the first 20 seconds, promise what the viewer will understand by the end. Keep
  that promise.
- Short, plain sentences. Vary their length, and use a real question now and then.
  Write numbers the way they're said ("nineteen seventy-one" is fine as "1971").
- Use concrete nouns: footage is found by the subject of each sentence. A line about
  "cats in wooden boxes" gets cats; a line about "the human condition" gets nothing.
- Maps: the first line naming a country, city or landmark can become an animated map
  with a pin (at most 4 per video, spread through the story). Name places plainly
  ("at Kinderdijk", "the Maeslant barrier"). Cities over 100,000 people and every
  country are known. Add a landmark, region or small town to
  `content/data/places.json` with its coordinates from Wikipedia before rendering.
- Every 60–90 seconds, add a turn: a surprise, a reversal, or a question answered.
  That's what holds retention.
- Never "delve", "journey", "tapestry", "in the realm of", "profound", "multifaceted",
  "fast-forward", or "as we navigate". Never say "chapter" or "part".
- End with one line that sticks, then the CTA exactly as written above.
- Write about real people respectfully and accurately. Use no invented quotes: only
  quote what a source shows they said.

## 4. Reviewing the render (contact-sheet critique)

Run `scripts.qa_report <run_id>`, then make each pass on its own, looking at the pictures
in `storage/review/<run_id>/qa/`:

1. **One second.** Glance at `sheet.png` and look away. What did you see? If the answer
   is "lots of stock footage", nothing leads.
2. **Line by line.** In the scene list, does each picture show what its line says? A
   loose match is acceptable for abstract lines. A wrong person, wrong place, wrong era,
   or a recognisable stranger is not.
3. **Sameness.** The same kind of shot three times in a row (three skies, three
   laptops) is the template showing.
4. **Opening.** In `opening.png`, the first 5 seconds must be the most striking images in
   the video.
5. **Ending.** `end.png` must be the disclaimer card. The shot before it must close the
   story, not be a leftover.
6. **Phone test.** Shrink the thumbnail to a third. Can you still read every word and
   tell what the picture is? Does it match the story?
7. **Substance.** Is every number on screen or in the narration in the sources file?

Score each 1–10: **pictures 40%** (right subject, striking, varied), **clarity 30%** (the
point of each scene is readable on a phone), **idea 20%** (a story with a turn, not a
list), **content 10%** (specific and true). An untrue claim caps content at 4. Fix that
before anything else. If your first score for your own video is 9, score it again as
someone who didn't make it.

Write down the three biggest problems, each with the frame it shows in and the fix. Fix
them in this order: anything untrue, then wrong pictures, then the hook and ending, then
search text, then detail.

## 5. Search and social

- **Title:** 70 characters at most, with the main keyword in the first 40, for example
  "Japan", "Meiji", "motivation" or "Rome". Curiosity without a lie: the video must
  answer what the title asks.
- **Thumbnail text:** 2–4 words that add to the title rather than repeat it.
- **Description:** the first two lines carry the keyword and the promise. The disclaimer
  and credits are added automatically.
- **Tags:** 8–15 phrases people really search: names, places, events, ideas in the video.
  No single filler words.

---

Parts of section 4 (the separate passes, the weighted score with caps, "score it again as
someone who didn't make it") are adapted from the `video-design` skill's `critique.md` in
[digitalsamba/claude-code-video-toolkit](https://github.com/digitalsamba/claude-code-video-toolkit)
(MIT), which itself adapts [taste-skill](https://github.com/Leonxlnx/taste-skill) (MIT).
