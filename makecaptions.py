#!/usr/bin/env python3
"""
makecaptions.py — turn a word-level transcript + a cut list into caption cues on the
OUTPUT timeline, chunked into short reel-style lines.

  python3 makecaptions.py TRANSCRIPT.json --cuts "42.6-52.5,97-119" [--out cues.json]
      [--max-words 4] [--max-chars 24] [--gap 0.45] [--corrections corrections.json]

- Keeps only words whose start falls in a kept range; remaps each to output time
  (concatenated, in cut order), so it matches what stagereel.swift renders.
- Breaks a line on: sentence punctuation (. ? !), a pause > --gap, or the word/char cap.
- --corrections is an optional {"wrong":"right"} map applied to the FINAL line text
  (case-insensitive whole-word), for fixing known mishears once, everywhere.
Output: [{"start","end","text","words":[{start,end,text}]}, ...] (words = karaoke timing) — hand-proof the text, then feed to stagereel.swift.
"""
import argparse, json, re, sys
from pathlib import Path

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript")
    ap.add_argument("--cuts", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--max-words", type=int, default=4)
    ap.add_argument("--max-chars", type=int, default=24)
    ap.add_argument("--gap", type=float, default=0.45)
    ap.add_argument("--corrections", default=None)
    a = ap.parse_args()

    ranges = []
    for piece in a.cuts.split(","):
        lo, hi = piece.split("-"); ranges.append((float(lo), float(hi)))

    corr = {}
    if a.corrections:
        corr = json.load(open(a.corrections))

    doc = json.load(open(a.transcript))
    words = []
    for seg in doc["segments"]:
        for w in seg.get("words", []):
            words.append(w)
    words.sort(key=lambda w: w["start"])

    # remap kept words to output time
    kept = []  # (out_start, out_end, text)
    offset = 0.0
    for (lo, hi) in ranges:
        seg_words = [w for w in words if lo <= w["start"] < hi]
        for w in seg_words:
            os_ = (w["start"] - lo) + offset
            oe_ = (min(w["end"], hi) - lo) + offset
            kept.append((os_, oe_, w["word"].strip()))
        offset += (hi - lo)

    # chunk into lines
    cues, cur = [], []
    def flush():
        if not cur: return
        text = " ".join(t for _, _, t in cur)
        text = re.sub(r"\s+([.,!?;:])", r"\1", text).strip()
        def fix(s):
            for wrong, right in corr.items():
                s = re.sub(rf"\b{re.escape(wrong)}\b", right, s, flags=re.IGNORECASE)
            return s
        text = fix(text)
        # karaoke renders the per-word text, so corrections must reach the words too
        cues.append({"start": round(cur[0][0], 2), "end": round(cur[-1][1] + 0.12, 2), "text": text,
                     "words": [{"start": round(ws, 2), "end": round(we, 2), "text": fix(wt)} for ws, we, wt in cur]})
        cur.clear()

    for i, (os_, oe_, t) in enumerate(kept):
        if cur:
            prev_end = cur[-1][1]
            joined = " ".join(x[2] for x in cur) + " " + t
            if (os_ - prev_end) > a.gap or len(cur) >= a.max_words or len(joined) > a.max_chars:
                flush()
        cur.append((os_, oe_, t))
        if re.search(r"[.!?]$", t):   # break after sentence enders
            flush()
    flush()

    # make contiguous: each caption holds until the next begins (no overlap, no mid-speech flicker)
    for i in range(len(cues) - 1):
        cues[i]["end"] = round(cues[i + 1]["start"] - 0.02, 2)
    # per-word karaoke timing: each word is "active" until the next word starts (last one to cue end)
    for c in cues:
        ws = c["words"]
        for j in range(len(ws)):
            ws[j]["end"] = ws[j + 1]["start"] if j + 1 < len(ws) else c["end"]

    out = a.out or str(Path(a.transcript).with_suffix("").as_posix()) + "_cues.json"
    Path(out).write_text(json.dumps(cues, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[makecaptions] {len(cues)} cues over {offset:.1f}s of kept footage -> {out}")
    for c in cues:
        print(f"  {c['start']:6.2f}-{c['end']:6.2f}  {c['text']}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
