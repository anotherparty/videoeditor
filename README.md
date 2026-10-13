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
