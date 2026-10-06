#!/usr/bin/env python3
"""
deadair.py — turn a word-level transcript into a --cuts list that drops dead air.

  python3 deadair.py TRANSCRIPT.json [--gap 0.7] [--pad 0.15] [--within "12.0-58.5"]

- Groups consecutive words whose silence between them is <= --gap into one kept range.
- Pads each range by --pad (a breath before/after) so cuts don't clip consonants.
- --within restricts to one source window (for pulling a short reel out of a long take).
- Presets: natural = --gap 0.7, tight = --gap 0.35, light = --gap 1.5.
Prints the cut string (feed straight to makecaptions.py / stagereel.swift --cuts) and,
on stderr, how much time was removed.
"""
import argparse, json, sys

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript")
    ap.add_argument("--gap", type=float, default=0.7)
    ap.add_argument("--pad", type=float, default=0.15)
    ap.add_argument("--within", default=None)
    a = ap.parse_args()

    t = json.load(open(a.transcript))
    words = [w for s in t["segments"] for w in s.get("words", [])]
    lo, hi = 0.0, float(t.get("duration") or 1e9)
    if a.within:
        lo, hi = (float(x) for x in a.within.split("-"))
    words = [w for w in words if w["start"] >= lo and w["end"] <= hi]
    if not words:
        print("no words in range", file=sys.stderr); return 1

    ranges = []
    s, e = words[0]["start"], words[0]["end"]
    for w in words[1:]:
        if w["start"] - e <= a.gap:
            e = max(e, w["end"])
        else:
            ranges.append((s, e)); s, e = w["start"], w["end"]
    ranges.append((s, e))

    # pad, clamp, and merge anything the padding made touch
    out = []
    for s, e in ranges:
        s, e = max(lo, s - a.pad), min(hi, e + a.pad)
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], e)
        else:
            out.append((s, e))

    kept = sum(e - s for s, e in out)
    span = (hi if a.within else float(t.get("duration") or out[-1][1])) - lo
    print(f"[deadair] {len(out)} ranges, kept {kept:.1f}s of {span:.1f}s "
          f"(cut {span - kept:.1f}s)", file=sys.stderr)
    print(",".join(f"{s:.2f}-{e:.2f}" for s, e in out))
    return 0

if __name__ == "__main__":
    sys.exit(main())
