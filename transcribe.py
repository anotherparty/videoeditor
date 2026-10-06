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
"""
import argparse, json, os, sys
from pathlib import Path

def ts(sec: float) -> str:
    sec = max(0.0, float(sec))
    m, s = divmod(int(round(sec)), 60)
    return f"{m:02d}:{s:02d}"

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--model", default="base.en")
    ap.add_argument("--out-dir", default=str(Path(__file__).parent / "transcripts"))
    a = ap.parse_args()

    src = Path(a.input).expanduser()
    if not src.exists():
        print(f"ERROR: input not found: {src}", file=sys.stderr); return 1
    out_dir = Path(a.out_dir).expanduser(); out_dir.mkdir(parents=True, exist_ok=True)
    stem = src.stem

    from faster_whisper import WhisperModel
    print(f"[transcribe] loading model {a.model} (int8)…", flush=True)
    model = WhisperModel(a.model, device="cpu", compute_type="int8")

    print(f"[transcribe] transcribing {src.name} …", flush=True)
    segments, info = model.transcribe(str(src), language="en", word_timestamps=True,
                                      vad_filter=True)

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
        json.dumps({"source": str(src), "model": a.model, "duration": dur,
                    "segments": seg_list}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[transcribe] {len(seg_list)} segments, ~{ts(dur)} long", flush=True)
    print(f"[transcribe] wrote {out_dir/f'{stem}.txt'}", flush=True)
    print(f"[transcribe] wrote {out_dir/f'{stem}.json'}", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
