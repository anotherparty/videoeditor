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
- 📰 article.py + articlecard.swift (in progress): URL + exact passage -> clean news-page card with the highlighter sweep.
  find_articles(): Claude searches the web for up to 2 articles backing what Adam says; each passage is checked
  word-for-word against the fetched page. Not wired into autoplan yet.
- ✂️ How tight? (Oct 12 2026): project setting `edit` = light (long pauses) / clean (+ every um and uh, default) /
  ruthless (shorter pauses + stutters and doubled words). transcribe.py --fillers makes Whisper write the ums down
  (one-year: 0 -> 6 found); deadair.py --drop-fillers/--drop-repeats cuts them. The Look section shows seconds each
  option cuts (one-year: 37 / 42.5 / 47.6 s of 3:33). Changing it re-cuts every video; the look stays approved.
- ✋ Drop B-roll on the timeline (Oct 12 2026): a Wide video card has a library tray above its timeline. Drag a thumb
  (or a Finder file) onto the timeline: the drop's x position becomes the transcript time (3.8 s long) and is saved as
  hand-placed B-roll (`manual_broll`, same as a transcript-line drop). It shows as a dashed block until the next render.

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
