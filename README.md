# Reel Studio (Another Party video editor)

Turns a talking-head phone video into a full cut plus vertical reels, automatically: dead air cut, karaoke
captions that never cover the speaker's face, name labels, place/date cards, emoji pops, stock B-roll,
screenshots with highlighted lines, split-screen layouts, title card, end card. macOS only, no installs
beyond the system Swift/Python (AVFoundation + Vision do the video and face/text work).

## Run the dashboard

```
python3 dashboard/server.py        # http://localhost:8777
```

Make a project, drop in the video (and any screenshots of articles/posts/letters), set the title card and
caption style, press **Make the videos**. Every planned graphic is listed per video with an on/off switch;
switching one off re-renders just that video. Download full-quality or phone copies, mark what's posted.

Projects live in `~/Projects/Reels/<name>/` (older folders can be listed in `Reels/_index.json`).

## Presets (the look gets better every project)

`presets/<name>.json` holds a reusable look: caption style, end-card text, link, loudness, and `notes`, a
list of lessons learned. A new project starts from its preset (`another-party` by default). After you've
tuned a project's look, press **Save this look to the preset** in section 2 of the dashboard and optionally
type a lesson. Every project after that starts from the improved version. Title card, date and reel tags
stay per project. When Claude works on a project, it reads the preset's `notes` first and follows them.

**Project types (Oct 12 2026).** The dropdown under "New project name" picks the preset: Another Party,
Talking head (btb captions), Panel / interview (box captions, "Watch the full panel"), Comics / book club
(typewriter captions, @adam_drawseverything). Each is just a file in `presets/`; add a file to add a type.
Planned next: Post panel (caption + hashtag sets per account, YouTube Shorts / Instagram post buttons,
Substack draft), a CapCut-style drag timeline, and more B-roll options.

**Your B-roll library (Oct 12 2026).** Put your own photos/clips (.jpg .png .mp4 .mov) in
`~/Projects/Reels/_library/`, named for what they show: `lexi-couch.jpg`, `sing-sing-yard.mov`. When a
video says the name (or any word of 4+ letters in it), that file plays as B-roll, ahead of Pixabay stock.
For other trigger words, add `library.json`: `{"lexi-couch.jpg": ["Lexi", "my dog"]}`. Re-run
Re-pick/Render to pick up new files. Next B-roll steps: Ken Burns + PiP, quote/stat cards, archival
stills, drag-onto-a-transcript-line.

**Ken Burns + PiP (Oct 12 2026).** Photos take turns: zoom in, pan left, zoom out, pan right (`kb`:
in|out|left|right|up|down|none). Video B-roll can be `"layout": "pip"`: the clip fills the screen and Adam's
whole frame slides into a cream-framed box bottom-right (34% size, above the captions), then grows back.
Library clips default to PiP; Pixabay clips stay split screen. Next: news-style lower thirds, quote/stat cards.

**News bars (Oct 12 2026).** Red-and-white TV lower third (white headline bar, red edge and red rule; optional `kicker` word adds a red tab), only on
the strongest lines: autoplan scores comma-sized phrases (strong words like parole/Attica/never, registry
names, years, "didn't/finally/since"), needs a score of 4+, max one per 40s, 30s apart. The headline is the
phrase with filler and dangling words trimmed, 8 words max. Switch any one off in the dashboard plan list.

**Quote + stat cards (Oct 12 2026).** Quote card: cream full screen, the line in big black type with its
strongest word in red, a red serif quote mark, "— ADAM ROBERTS", Adam in the corner bubble; the best strong
phrase the news bars didn't use, one per video. Stat card: the number + unit said most often ("24 HOURS",
"two hours" -> 2 HOURS) as a huge red number. Captions hide while a card is up (the card shows the words).

**Quote types on (Oct 13 2026).** The quote card's line now types on letter by letter instead of sliding in: the
same text image, masked by one strip per line that widens a letter at a time (discrete CoreAnimation steps), with a
red caret riding the last letter. A letter shows up to where the next one starts (Avenir Heavy caps overhang their
advance, so cutting at the advance left half an A). Typing starts 0.1 s in and takes 0.04 s a letter, capped at 55%
of the card, so the full line holds for reading; the caret stays 0.7 s after the last letter, and "— ADAM ROBERTS"
fades in when typing ends. Stat cards are unchanged. Tested on a 4.5 s card ("I got a fellowship at Sing Sing
Prison Museum this summer"): frames at 6.25 / 6.5 / 6.9 / 7.2 / 7.6 / 8.0 / 8.3 / 8.6 s show I G| -> FE| -> A| ->
PRISO| -> SUMM| -> full; the finished card matches the old renderer's pixel for pixel (JPEG noise only).

**B-roll by hand (Oct 12 2026).** Dashboard section 4 shows the transcript as short lines and your library as
thumbnails. Drag a thumbnail (or a file from Finder) onto a line: it plays while that line is said (at least
2.5s), beats every automatic pick, and only the videos covering that moment re-render. ✕ removes it.
Stored as `manual_broll` [{path, start, end}] in project.json; pipeline passes it to autoplan `--manual`.
Photos get the Ken Burns rotation; clips go picture-in-picture.

**Drag timeline (Oct 12 2026).** Each video card's timeline: drag a block to move a graphic, drag its edge to
stretch it (snaps to 0.1s, tooltip shows the time). Overlapping blocks get their own row; 28px per second,
scrolls sideways, gridline every 5s; "⤢ Wide" stretches the card across the page. Saved as
`work/<video>.moves.json` {id: [start, end]} (transcript time); autoplan gives moved items your span, always
on, and automatic picks avoid it. "Reset moves" clears them. Positions are transcript time, so a block sits
slightly off from the rendered video where dead air was cut.

**Post panel (Oct 12 2026).** Under each finished video: ✍️ Write caption (Claude Code CLI, `claude -p`, Adam's
subscription; prompt = ~/.config/another-party/caption_prompt.md, built from his my-writing-style + ig-caption skills,
private), editable caption + hashtags (registry/accounts.json default set for @anotherparty25), alt text, flags,
🖼 Make cover / Another frame (cover.swift, +5s per click), 📋 Copy (server-side pbcopy), ⬇ Video, Open Instagram.

**Overhaul (Oct 12 2026).**
- Safety: the server only answers requests to localhost, and changes only from the dashboard page (Origin check, blocks
  other websites and DNS rebinding). All JSON writes are atomic (temp + rename); the pipeline writes back only the keys
  it changed, so dashboard edits made during a render survive. Re-render keeps the old video in out/_prev/ (shown
  until the new one exists); Health check can delete them. Jobs run in their own session with work/pipeline.pid, so a
  dashboard restart neither kills nor forgets a render. Mac notification when a render/preview finishes or fails.
- Project page: step bar (Footage, Look, Videos, Post) with the next step highlighted; finished sections fold up
  (click a heading to open; remembered). Timeline playhead follows the video (work/<video>.cuts.txt maps video time to
  transcript time); click a block to jump there. Spacebar plays/pauses. Archive moves a project to Reels/_archive/.
  The page only redraws when something changed and never while a video is playing. Every graphic kind has a color.
- ✨ Inspiration page: drop screenshots/clips or paste links (YouTube shows its thumbnail). Each asks "What is it you
  like about this?" (captions, colors, pacing, B-roll, text cards, transitions, sound, framing, hook, other + a note)
  and "Use for…" a project type; that writes a lesson into the preset's notes (removed again if the item is deleted).
  Stored in ~/Projects/Reels/_inspiration/ (not in this repo).
- 🎞 Library page: drop files in, rename to change trigger words, remove. 🩺 Health check: Claude signed in (Test
  button), caption style file, Pixabay key, transcription, disk space, nightly backup, storage + cleanup.
- 🏛 Archival stills (Oct 12 2026): a registry place with `archive` gets a public-domain Wikimedia Commons photo
  ("ARCHIVE PHOTO", Ken Burns, you in a corner bubble) for 3.5 s right after its place card, or instead of stock.
  Fix: the photo was always dropped because the 0.4 s gap rule counted its own place card as an overlap; card + photo
  are now checked as one span. Proven on the Sal reel (Attica 1971 photo at 12-15 s, audio unchanged).
  A place can pin one exact Commons file (`archive_file` in registry/places.json); a pinned CC BY / CC BY-SA photo
  shows its credit on screen ("PHOTO: Jayu · CC BY-SA 2.0"). Attica now uses the 2007 front-gate shot, not the riot photo.
  Write caption also ends the caption with "Photo: Jayu, CC BY-SA 2.0 (creativecommons.org/licenses/by-sa/2.0)"
  for every credited photo that's switched on in that video (added by code, not by Claude).
- 🗂 Project B-roll (Oct 12 2026): section 4 has a "Drop photos and clips for this project" box -> source/broll/. They show
  first in the tray (red border) to drag onto a line or the timeline, and auto-place when their file name is said (same
  rules as the library, project files first). Footage box safety: once a main video exists, another video dropped there
  goes to project B-roll and never replaces it; "Replace main video…" (with a confirm) is the only way to swap it.
- 📰 article.py + articlecard.swift: URL + exact passage -> clean news-page card with the highlighter sweep.
  find_articles(): Claude searches the web for up to 2 articles backing what Adam says; each passage is checked
  word-for-word against the fetched page.
- 🗞 Article cards in the reels, automatically (Oct 13 2026): autoplan step 1b runs find_articles once per project over
  the whole transcript (cached in work/articles.json), makes each card once (work/articles/), and any video whose cuts
  hold the moment gets a split card (article top, Adam bottom, "kb": "none") starting on the word that names it, 6.5 s
  of finished-video time (skipped under 4 s; never opens on the last sliver before a cut). ON by default, plan id
  article:<domain>, why = outlet: headline (url); dashboard row shows "🗞 outlet: headline" + an "outlet ↗" link, own
  colour, normal off switch. FIND_PROMPT tightened: the headline must be about the exact thing he names (same prison,
  program, law, event, film, statistic); same broad topic is rejected (the old marijuana-legalization pick for the
  visitor-with-marijuana story is the named counter-example), no personal anecdotes. Code checks too: Claude must name
  the shared subject ("about") and one of its words must be in the headline; pages with no body paragraphs are skipped.
  Tested: Phil transcript (zz copy of another-day-in-paradise) -> 0 picks in 3 of 3 runs (the old prompt took the
  legalization story); one-year (zz copy) -> 2 picks, News 12's Sing Sing Prison Museum dropped (passage not word-for-word),
  WYSO's "'Shawshank Redemption' turns 30" kept, on "Shawshank" at 33.2 s. Rendered reel_redemption + full: card on for
  6.5 s, highlight sweeps in 0.6 s after it appears, headline/body readable, Adam's head under the seam, never covered;
  loudness peak -0.9 / RMS -17.3 (reel) and -17.5 (full) dBFS. Switching it off on the dashboard wrote off.json and the
  re-plan kept it listed, off, with a B-roll photo taking the gap.
- 🗞 Article card fixes (Oct 13 2026, after review): (1) the card only starts on a word that names the subject ("about"
  words) said in this video's cuts, searched in every line holding Claude's t or starting within 1 s of it; no more
  "line start" fallback. Claude's t=85.5 sat on the end of the line before "I got a fellowship at Sing Sing Prison
  Museum", so the River Journal card landed at 62.9 s in reel_redemption (a reel that never says Sing Sing). Now that
  reel gets no card, and reel_off + full get it on "Sing" at 89.31 s. (2) Long site names are cut to the outlet
  (article.short_outlet: "River Journal Online - News for Tarrytown, ..." -> "River Journal Online") on the card and in
  the plan; the dashboard link also shrinks with "…" (max 34% of the row) so the headline and off switch always show.
  (3) If Claude fails or times out, work/articles.failed is written and the finder is not asked again for 6 h, so a
  project's other videos don't each wait up to 420 s.
- ✂️ How tight? (Oct 12 2026): project setting `edit` = light (long pauses) / clean (+ every um and uh, default) /
  ruthless (shorter pauses + stutters and doubled words). transcribe.py --fillers makes Whisper write the ums down
  (one-year: 0 -> 6 found); deadair.py --drop-fillers/--drop-repeats cuts them. The Look section shows seconds each
  option cuts (one-year: 37 / 42.5 / 47.6 s of 3:33). Changing it re-cuts every video; the look stays approved.
  Render-tested Oct 13 2026 (full one-year video on clean and ruthless): captions showed "uh," / "Um," (the dropped
  word's start fell inside the 0.03 pad) and ruthless cut "Sing Sing" to "Sing". Fixed: makecaptions.py never shows
  um/uh in any mode (nor a cut word whose middle is outside the kept range); real doubles (Sing Sing, had had) are never
  stutters; Whisper's filler edges were 0.1-0.3 s off and the 0.03 pad clipped "painting" mid-word (cut at -26 dB),
  so transcribe.py now writes `<video>.env.json` (loudness every 10 ms; `--env-only` for older transcripts, the
  pipeline adds it when missing) and deadair.py snaps each cut next to a dropped word into the nearest real silence.
  Every filler cut now lands at -47..-55 dB source level except where speech runs straight through (Freeman-uh-as:
  the quietest dip, -36). Clean cuts 41 s, ruthless 46 s; both measure peak -0.9 / RMS -17.3 dBFS. The status pill
  says "Needs a re-render" (not "All videos ready") after a setting change sends a video back.
  Oct 13 2026 review fix: ordinary pause cuts still used a blind 0.15 pad, so ruthless (gap 0.35) cut 80 ms out of
  speech after "Huntington" (-19 dB) and every mode clipped "yeah" (38.80, -14 dB) and the "-ing" of "painting."
  (125.64, -29 dB). deadair.py now cuts a pause only inside the longest real quiet stretch between the two words
  (local floor + 6 dB, never above -40 dB; blips under 120 ms bridged), keeping 0.15 s of it each side; no silence =
  no cut. Every non-filler cut edge in light / clean / ruthless now sits at -40 dB or quieter (was 11 / 14 / 17 louder
  edges). Honest cut totals are smaller: light 27 s, clean 34 s, ruthless 36 s (were 37 / 41 / 46). The Freeman-uh cut
  stays at 40.40: Whisper on the source shows "Freeman" runs 40.03-40.33 (the 39.94 dip is its "f"). Re-rendered on
  clean and ruthless: no um/uh in captions or heard by Whisper in the render, peak -0.9 / RMS -17.5 dBFS both.
  The pill also says "Needs a re-render" while a look preview is waiting (state "preview ready") and it was sent back.
- ✋ Drop B-roll on the timeline (Oct 12 2026): a Wide video card has a library tray above its timeline. Drag a thumb
  (or a Finder file) onto the timeline: the drop's x position becomes the transcript time (3.8 s long) and is saved as
  hand-placed B-roll (`manual_broll`, same as a transcript-line drop). It shows as a dashed block until the next render.
- 📷 Photos in the Footage box become B-roll (Oct 12 2026): an image dropped in Footage is read with ocr.swift. 6 or fewer
  text lines = a photo -> project B-roll (source/broll/); more = a highlighted screenshot card as before. A camera-less
  image whose big text fills 30%+ of the frame (a title card, e.g. Phil's "Another Day In Paradise" cover, 6 lines) stays
  a card; camera photos (EXIF make) with a sign or a shirt go to B-roll. Tested on 17 real images: all 14 one-year photos
  -> B-roll, all 3 Another Day screenshots -> cards. HEIC/HEIF is converted to .jpg with sips (the jpg is kept, the HEIC
  dropped) for Footage, project B-roll, transcript/timeline drops and the library. one-year migrated: all 14 shots were
  photos, copied to source/broll/ (IMG_3699.HEIC -> IMG_3699.jpg; IMG_6227 6233 6387 6389 6397 6398 6399 6400 6415 6448,
  photo-18321 18382 18408) and taken out of `shots` (now empty); the originals stay in source/.
  Follow-up (Oct 12 2026): moving a photo into source/broll/ or converting a HEIC never overwrites a different file of
  the same name (it becomes NAME-1.jpg; the identical file dropped again is reused, no duplicate). The live dashboard was
  restarted after the last edit and re-tested on it: the 6-line title card stays a card, a 2nd photo named IMG_6400.JPG
  lands as IMG_6400-1.JPG. _library/IMG_3699.HEIC (copied in before this) converted to IMG_3699.jpg.
- 🖼 Claude places every B-roll file (Oct 12 2026): any file in source/broll/ that no spoken name matched (camera names
  like IMG_6400.JPG) gets a moment chosen by Claude. autoplan.py makes small jpgs (videos: one frame) in
  work/auto/broll_thumbs/, then ONE `claude -p` call (Read tool allowed) with the transcript lines + times; Claude says what
  each picture shows and its best moments (up to 3). Cached in work/broll_auto.json by file name + mtime (no re-asking on
  re-render; a changed file is asked again). The moment snaps to the matching word in that line ("tree") and slides to
  the nearest free spot (30 s later / 10 s earlier, keeping 1.5 s of Adam between pictures). It runs after news bars /
  quote / stat cards (those come from his exact words); a name-matched library file keeps its earlier priority. No
  Claude (REELSTUDIO_NO_CLAUDE=1, signed out, timeout) or no fitting moment -> spread evenly into the gaps left, never two
  within 6 s, never in the first 3 s. All ON, photos Ken Burns, clips picture-in-picture; plan "why" = what Claude saw +
  the line. Dashboard: own colour, "🖼 file" in the plan list with the usual off switch. In a reel, only pictures whose
  moments fall inside its window appear.
  Renderer fixes found in the test: (1) 3+ phone HEVC clips on one PiP track failed to compose (-11841); clips now
  alternate between two tracks. (2) A small source (one-year's 576x1024 video, rotated with tx=1080) sat in a corner
  of the frame; stagereel now scales any source to fill 1080x1920 (k = 1 for normal phone video, so no change there).
  Tested on zz-autobroll (one-year video + its 17 B-roll files): Claude placed 17 of 17 in 46 s, the full render was
  checked frame by frame at every placement (tree photos on "tree... right outside", sunset sky on "I watched the sun go
  down", paintings and marker clips on "I painted for people"), Adam's face in the bubble/PiP box, never covered;
  loudness peak -0.9 / RMS -17.4 dBFS. Switching one off on the dashboard dropped it on re-plan; the others stayed.
- 🖼 B-roll spacing + honesty fixes (Oct 12 2026, late): a review render showed two sky photos 0.38 s apart (a cut
  between them shrank the 1.5 s gap). Gaps are now measured in finished-video time (`out_t` / `ofree` in autoplan.py):
  1.5 s of Adam between pictures, 6 s between spread pictures, and each picture must be on screen at least 2.5 s
  (one used to straddle a cut and flash for 1.4 s). Claude's picks now slide only within the line he's saying at that
  moment (3 s back if no line); a picture whose lines are all taken goes to the even spread and its "why" says so,
  instead of landing up to 30 s away under an unrelated line. A name-matched file whose library slot was skipped for
  overlap no longer shows twice (the skipped twin is dropped once the auto copy is on). A file you switched off is not
  sent to Claude. Dashboard: the plan-list switch now stays where you put it (toggle also writes plan.json).
  Tested on zz-flicker (one-year + 17 B-roll files): closest gap between any two graphics 1.52 s on screen, spread
  pictures 8.1 s apart, no-Claude plan 17/17 on and 6.09 s apart; frames checked at every graphic and every gap;
  loudness -0.9 / -17.4 dBFS. 8 of 17 pictures sit on a line Claude picked; 9 are spread (four sunset shots all wanted
  the one "sun go down" line), so those are the ones to switch off if they don't fit.
- 🎞 Claude picks the reels (Oct 13 2026): reelpick.py hands Claude the numbered sentences (with times) and asks for
  up to 4 stand-alone stories: a start that needs no earlier context, a real ending, natural length (about 15-75 s,
  never padded to a round number), no overlaps. Its picks are checked (whole sentences, 12-90 s, no overlap) and the
  keyword scorer is the fallback (no Claude / REELSTUDIO_NO_CLAUDE=1 / nothing usable). The keyword scorer itself now
  only ends a reel where a sentence ends (one-year's first pick stopped on "after decades," before the Shawshank line)
  and loses points for starting mid-sentence; a reel with no named person gets its punchiest phrase as the tag instead
  of its first five words ("And so it's when I"). Reel names come from the tag's last word (reel_living, not reel_ive).
  Reel windows now keep up to 0.3 s of air past the first/last word (never into a neighbour word); it was 0.05 s,
  which clamped deadair's pad on the last word. Two plan fixes found in the one-year QA: a homophone number word
  ("two", "four", "eight") before people/books/pages no longer makes a stat card ("I also painted four people" was
  "for people": a 4 PEOPLE card), and a two-word emoji key set to "" blocks the one-word emoji ("heart attack" no
  longer pops a ❤️). Tested on one-year: picks = tree to Shawshank to "a person in this society again" (60 s finished),
  ankle monitor at Sing Sing (32 s), painting inside to "I watched the sun go down" (51 s), "busy living" (29.5 s); full 3:02.
  Renderer + Post panel fixes from the same QA: (1) Adam's selfie (IMG_6400) had his bubble right on his face in the
  photo. stagereel now runs Vision on each B-roll still (faces + the head end of each person, since a head turned away
  isn't a face), maps them through the aspect-fill crop and the worst Ken Burns zoom/pan, and puts the bubble in the
  clearest corner (log: "NOTE: bubble moved br -> tl"). (2) iPhone photos with an HDR gain map load as 10-bit
  images that came out grey and washed in the video; every still is now redrawn as 8-bit sRGB (long side <= 2400 px).
  (3) Captions were fed every transcript line touching the reel window, so a neighbour sentence leaked in; now only
  lines whose middle is inside it. (4) Hashtags are cleaned to #word ("#ankle monitor" -> #anklemonitor). (5) Alt
  text was a guess ("outdoors near Kerber Farms" for a bookshop talk): write_caption now adds "What's on screen", one
  cached Claude look at a frame of the main video (work/scene.json) plus what Claude saw in each picture the video shows.

## Pieces

| file | job |
|---|---|
| `pipeline.py` | one project in, all videos out (the dashboard runs this) |
| `transcribe.py` | word-level transcript (faster-whisper) |
| `deadair.py` | cut list that removes pauses |
| `makecaptions.py` | caption cues from the transcript |
| `reelpick.py` | picks the reel-worthy stretches |
| `autoplan.py` | plans labels, place cards, emoji, stock B-roll, screenshot cards |
| `editplan.py` | turns the plan into output-time edits |
| `brollcard.swift` | screenshot → 9:16 or split card, OCR'd highlighter marks |
| `stagereel.swift` | the renderer (captions, graphics, split screen, title/end cards) |
| `normalize.swift` | brings speech up to reel loudness (default -15 dBFS) with a peak limiter |
| `loudness.swift` | prints peak / RMS levels of any video |
| `ocr.swift`, `grabframes.swift`, `sheet.swift`, `cover.swift`, `compress.swift` | helpers |
| `presets/` | saved looks + lessons; new projects start from one |
| `registry/` | people, places, emoji the planner knows (`people.json` is private; see `people.example.json`) |

## Setup notes

- Transcription uses a Python venv with `faster-whisper` (path set in `pipeline.py`, `VENV_PY`).
- Stock footage uses a Pixabay API key read from `~/.config/another-party/pixabay_key` (never commit it).
- The logo path is a `--logo` flag on `stagereel.swift`; the default points at the Another Party brand file.
- 🚀 Post button (Oct 13 2026): Post panel button posts one video to YouTube (Another Party) and/or Instagram
  (@anotherparty25) after a confirm box. posting.py runs as its own process: under-10MB upload copy, post_prompt.md,
  claude -p --chrome drives Adam's signed-in Chrome (YouTube Studio, then Meta Business Suite), checks before ever
  re-pressing Share, writes posting[<video>] + post_jobs status (log: work/posting.log). Allowed by Adam's own
  autoMode rule in ~/.claude/settings.json. Tested: dry run (Sal reel), cancel sends nothing, no-caption stops safely.
  A real publish runs the first time Adam presses Post.
