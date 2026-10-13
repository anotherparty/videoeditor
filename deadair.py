#!/usr/bin/env python3
"""
deadair.py — turn a word-level transcript into a --cuts list that drops dead air.

  python3 deadair.py TRANSCRIPT.json [--gap 0.7] [--pad 0.15] [--within "12.0-58.5"]

- Groups consecutive words whose silence between them is <= --gap into one kept range.
- Pads each range by --pad (a breath before/after) so cuts don't clip consonants.
- --within restricts to one source window (for pulling a short reel out of a long take).
- Presets: natural = --gap 0.7, tight = --gap 0.35, light = --gap 1.5.
- --drop-fillers cuts um/uh/ah/er/hmm (needs a transcribe.py --fillers transcript);
  --drop-repeats also cuts stutters and doubled words ("I- I", "the the"). Cuts next to a dropped word get a tiny pad.
Prints the cut string (feed straight to makecaptions.py / stagereel.swift --cuts) and,
on stderr, how much time was removed.
"""
import argparse, json, sys

FILLERS = {"um", "uh", "umm", "uhh", "uhm", "ah", "er", "erm", "hmm", "mm"}

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript")
    ap.add_argument("--gap", type=float, default=0.7)
    ap.add_argument("--pad", type=float, default=0.15)
    ap.add_argument("--within", default=None)
    ap.add_argument("--drop-fillers", action="store_true"); ap.add_argument("--drop-repeats", action="store_true")
    a = ap.parse_args()

    t = json.load(open(a.transcript))
    words = [w for s in t["segments"] for w in s.get("words", [])]
    lo, hi = 0.0, float(t.get("duration") or 1e9)
    if a.within:
        lo, hi = (float(x) for x in a.within.split("-"))
    words = [w for w in words if w["start"] >= lo and w["end"] <= hi]
    if not words:
        print("no words in range", file=sys.stderr); return 1

    norm = lambda w: w["word"].strip(" ,.?!;:\"").lower()
    drop = [False] * len(words)
    for i, w in enumerate(words):
        n = norm(w)
        if a.drop_fillers and n in FILLERS: drop[i] = True
        if a.drop_repeats and (n.endswith("-") or (i + 1 < len(words) and n and n == norm(words[i + 1]))): drop[i] = True
    dropped = sum(drop)

    ranges = []          # (start, end, start_touches_a_drop, end_touches_a_drop)
    cur = None
    for i, w in enumerate(words):
        if drop[i]:
            if cur: ranges.append((cur[0], cur[1], cur[2], True)); cur = None
            continue
        after_drop = i > 0 and drop[i - 1]
        if cur and w["start"] - cur[1] <= a.gap: cur[1] = max(cur[1], w["end"])
        else:
            if cur: ranges.append((cur[0], cur[1], cur[2], False))
            cur = [w["start"], w["end"], after_drop]
    if cur: ranges.append((cur[0], cur[1], cur[2], False))

    # pad, clamp, and merge anything the padding made touch
    out = []
    for s, e, sd, ed in ranges:
        s, e = max(lo, s - (0.03 if sd else a.pad)), min(hi, e + (0.03 if ed else a.pad))
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], e)
        else:
            out.append((s, e))

    kept = sum(e - s for s, e in out)
    span = (hi if a.within else float(t.get("duration") or out[-1][1])) - lo
    if dropped: print(f"[deadair] dropped {dropped} filler/repeat words", file=sys.stderr)
    print(f"[deadair] {len(out)} ranges, kept {kept:.1f}s of {span:.1f}s "
          f"(cut {span - kept:.1f}s)", file=sys.stderr)
    print(",".join(f"{s:.2f}-{e:.2f}" for s, e in out))
    return 0

if __name__ == "__main__":
    sys.exit(main())
