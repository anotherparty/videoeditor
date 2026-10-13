#!/usr/bin/env python3
"""
transcribe.py — word-level transcription for the stage-reel pipeline.

Uses the faster-whisper install already living in the wispr-flow-clone venv
(no ffmpeg needed; PyAV decodes the video/audio directly). Run it WITH that
venv's python:

  ~/Projects/wispr-flow-clone/.venv/bin/python transcribe.py INPUT.mov \
      [--model base.en|small.en|medium.en] [--out-dir DIR]

Writes two files next to each other in --out-dir (default ./transcripts):
  <stem>.txt   human-readable, [mm:ss] per segment  -> for marking cuts
  <stem>.json  {segments:[{start,end,text,words:[{start,end,word}]}]}  -> caption timing
  <stem>.env.json  {hop, db:[...]} loudness every 10 ms -> deadair.py puts filler cuts in real silence
  (--env-only writes just that, for a transcript made before it existed)
"""
import argparse, json, os, sys
from pathlib import Path

def ts(sec: float) -> str:
    sec = max(0.0, float(sec))
    m, s = divmod(int(round(sec)), 60)
    return f"{m:02d}:{s:02d}"

def write_env(src, out):
    """loudness envelope (dBFS per 10 ms) so cuts next to a dropped um can land in real silence"""
    import numpy as np
    from faster_whisper import decode_audio
    x = decode_audio(str(src), sampling_rate=16000); n = len(x) // 160
    db = 20 * np.log10(np.sqrt((x[:n * 160].reshape(n, 160) ** 2).mean(axis=1)) + 1e-9)
    out.write_text(json.dumps({"hop": 0.01, "db": [int(round(v)) for v in db]}))

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--model", default="base.en")
    ap.add_argument("--out-dir", default=str(Path(__file__).parent / "transcripts"))
    ap.add_argument("--fillers", action="store_true", help="keep um/uh/false starts in the transcript so they can be cut")
    ap.add_argument("--env-only", action="store_true", help="just write <stem>.env.json")
    a = ap.parse_args()

    src = Path(a.input).expanduser()
    if not src.exists():
        print(f"ERROR: input not found: {src}", file=sys.stderr); return 1
    out_dir = Path(a.out_dir).expanduser(); out_dir.mkdir(parents=True, exist_ok=True)
    stem = src.stem
    write_env(src, out_dir / f"{stem}.env.json")
    if a.env_only: return 0

    from faster_whisper import WhisperModel
    print(f"[transcribe] loading model {a.model} (int8)…", flush=True)
    model = WhisperModel(a.model, device="cpu", compute_type="int8")

    print(f"[transcribe] transcribing {src.name} …", flush=True)
    segments, info = model.transcribe(str(src), language="en", word_timestamps=True,
                                      vad_filter=True,     # a disfluent prompt makes Whisper write down the ums it normally hides
                                      initial_prompt="Umm, so, uh, I- I was, like, you know, um, I mean, uh, hmm." if a.fillers else None)

    seg_list, txt_lines = [], []
    for seg in segments:
        words = [{"start": round(w.start, 3), "end": round(w.end, 3),
                  "word": w.word} for w in (seg.words or [])]
        seg_list.append({"start": round(seg.start, 3), "end": round(seg.end, 3),
                         "text": seg.text.strip(), "words": words})
        line = f"[{ts(seg.start)}] {seg.text.strip()}"
        txt_lines.append(line)
        print("  " + line, flush=True)

    dur = seg_list[-1]["end"] if seg_list else 0.0
    (out_dir / f"{stem}.txt").write_text("\n".join(txt_lines) + "\n", encoding="utf-8")
    (out_dir / f"{stem}.json").write_text(
        json.dumps({"source": str(src), "model": a.model, "duration": dur, "fillers": a.fillers,
                    "segments": seg_list}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[transcribe] {len(seg_list)} segments, ~{ts(dur)} long", flush=True)
    print(f"[transcribe] wrote {out_dir/f'{stem}.txt'}", flush=True)
    print(f"[transcribe] wrote {out_dir/f'{stem}.json'}", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
