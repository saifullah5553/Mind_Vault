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

For a history documentary, TOPIC is one picture search per part of the story, so each
part shows its own subject:

```
TOPIC: Thingvellir + Almannagjá + Lögberg Thingvellir = Law Rock lawspeaker @ Thingvellir|rift|Law Rock; Ingólfr Arnarson + Icelandic turf house = booths farmers @ settler|Families|farmed; ...
```

- Parts are separated by `;`. After `@` come the words (`|` between them) that start
  that part: from the first line containing one, the lines show that part's pictures.
- `+` gives a part several searches; each gets an equal share of its pictures, so
  one subject can't fill the part. Use 4–6 concrete searches per part: landmarks,
  objects, people, old photographs, paintings.
- `= words` after a search lists the words the script uses for what that search
  shows, when the pictures are titled differently: Commons calls the Law Rock
  "Lögberg", so `Lögberg Thingvellir = Law Rock lawspeaker` puts those photos on the
  lines about the Law Rock and the lawspeaker.
- A start word shared by two parts (a country named early and in a later chapter)
  keeps the story in its current part; prefer words only one part uses.
- After the render, `qa/shotlist.txt` shows every line with its picture. A wrong
  picture means a missing search, a missing `= words` link, or a start word in the
  wrong place.

**AI illustrations (optional, $0, Cloudflare free allowance about 30 a day):** for
moments no real photo can show (the settlers arriving, the assembly in session,
daily life in a period), add a header line:

```
ILLUSTRATE: rode to a crack in the earth = wide shot of Viking Age settlers on horseback riding into a green rift valley in Iceland, about 930, wool cloaks, no buildings; camped in booths = ...
```

- `cue = prompt`, separated by `;`. The first line containing the cue shows the
  picture (once). Use 4–8 per video, at most 12, at moments that matter.
- Write the prompt like a shot description: shot size, who and what, place, period,
  clothing, light. Name the period and region; say what must NOT appear if the model
  might add it (no horned helmets, no dragon heads, no stone castles).
- Never for a real named person, a specific real object or document, or a real
  event's exact moment presented as a record. Those stay real photos.
- Each one is tagged "ILLUSTRATION" on screen, credited as AI, covered by the
  disclaimer, and declared to YouTube as altered or synthetic content automatically.
- Review each one like any picture: wrong period, invented lettering, fantasy
  details, modern objects. A bad one: rewrite the prompt and re-render.

Save the sources next to it as `content/scripts/<slug>.sources.txt`, one checked fact per
line, at least 8:

```
Commodore Matthew Perry's ships arrived at Uraga, near Edo, in July 1853 | https://www.britannica.com/...
```

Then plan the pictures before rendering (about 10 minutes):

```bash
.venv\Scripts\python -m scripts.run_pipeline --new-from-script content/scripts/<slug>.txt --category history --format long --plan-only
```

Use `--category psychology` for psychology topics. Read
`storage/images/<id>/picture_plan.txt` and look at `picture_plan.jpg`; fix every
wrong picture (lines marked `!!` first) in the script, plan again with
`--rerender <id> --from visual --script-file <file> --plan-only`, and render only a
clean plan (`--rerender <id> --from visual --script-file <file>`). A render costs
40–60 minutes; a plan costs 10. Never spend a render finding a wrong picture.

The camera (core/media/camera.py) films each photo like a director: it frames the
subject, pans across wide scrolls and maps, shows tall portraits whole, and cuts a
shot of 6 seconds or more from a wide view to a close-up when the photo is large.
So prefer large, sharp photos with one clear subject, and give long lines a
picture worth a close-up (a face, a seal, a ship, an inscription).

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
  A journey written as "from X to Y" ("they sailed from Norway to Iceland") becomes an
  animated route map, so write the key voyage, migration or march that way once.
- Pictures follow the words: each line gets the photo whose title and description
  share the most words with it. Name the concrete subject in the line (the Law Rock,
  turf houses, a longship) rather than an abstraction, and give each TOPIC part
  searches for the landmarks, objects and people its lines name. A line about an
  idea with nothing to show should still name a place or thing from that moment.
- Scenes follow the words too (core/media/scenes.py). The renderer picks the scene
  type from each line:
  - a line naming an **object** (a pot, coin, sword, brooch, tool, cloak) whose photo
    shows it becomes a **museum showcase** (the photo on a lit display with a label);
  - a **document** (a book, law, treaty, letter, inscription, manuscript) gets a
    warm-lit document showcase;
  - **digging, excavation, buried finds or carbon dating** become animated **soil
    layers** with the line's date glowing at its layer;
  - the first photo of a **named person or place** gets a name caption;
  - places and journeys get maps; years, spans and figures get date and number
    cards; quotations get a quote card; everything else gets the best-matching photo
    or clip.
  To get a showcase, name the object plainly in the line AND give the TOPIC a search
  for it, labelled with the line's word if the photos are titled differently
  (`Landnámabók manuscript = Book of Settlements book`). One object or document per
  minute is plenty; at most 6 showcases and 2 layer scenes per video.
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
