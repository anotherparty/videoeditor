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
