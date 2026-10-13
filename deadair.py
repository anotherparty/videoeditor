#!/usr/bin/env python3
"""
deadair.py — turn a word-level transcript into a --cuts list that drops dead air.

  python3 deadair.py TRANSCRIPT.json [--gap 0.7] [--pad 0.15] [--within "12.0-58.5"]

- Groups consecutive words whose silence between them is <= --gap into one kept range.
- Pads each range by --pad (a breath before/after) so cuts don't clip consonants.
- --within restricts to one source window (for pulling a short reel out of a long take).
- Presets: natural = --gap 0.7, tight = --gap 0.35, light = --gap 1.5.
- --drop-fillers cuts um/uh/ah/er/hmm (needs a transcribe.py --fillers transcript);
  --drop-repeats also cuts stutters and doubled words ("I- I", "the the"). Whisper's word edges are often 0.1-0.3 s off,
  so a cut next to a dropped word snaps into real silence using <transcript>.env.json (transcribe.py writes it):
  the first quiet stretch after the word before, the last one before the word after; else the quietest 10 ms.
- With the env map every plain pause cut also lands in real silence: it cuts only inside the longest quiet stretch
  between the two words (blips under 120 ms bridged), keeping --pad of it each side; no real silence = no cut.
  (Whisper's gaps are often a word's tail or a missed "yeah", not silence.)
Prints the cut string (feed straight to makecaptions.py / stagereel.swift --cuts) and,
on stderr, how much time was removed.
"""
import argparse, json, sys
from pathlib import Path

FILLERS = {"um", "uh", "umm", "uhh", "uhm", "ah", "er", "erm", "hmm", "mm"}
DOUBLES = {"sing", "had", "that", "is", "walla", "bora"}     # real doubled words ("Sing Sing", "had had"): never a stutter

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
        if a.drop_repeats and (n.endswith("-") or (i + 1 < len(words) and n and n == norm(words[i + 1]) and n not in DOUBLES)): drop[i] = True
    dropped = sum(drop)

    ranges = []          # (start, end, gap to a dropped word before start | None, gap to a dropped word after end | None)
    cur = None
    for i, w in enumerate(words):
        if drop[i]:
            if cur: ranges.append((cur[0], cur[1], cur[2], w["start"] - cur[1])); cur = None
            continue
        after_drop = w["start"] - words[i - 1]["end"] if i > 0 and drop[i - 1] else None
        if cur and w["start"] - cur[1] <= a.gap: cur[1] = max(cur[1], w["end"])
        else:
            if cur: ranges.append((cur[0], cur[1], cur[2], None))
            cur = [w["start"], w["end"], after_drop]
    if cur: ranges.append((cur[0], cur[1], cur[2], None))

    ev = Path(a.transcript).with_suffix(".env.json"); env = json.load(open(ev)) if ev.exists() else None
    if env: hop, db = env["hop"], env["db"]; quiet = sorted(db)[len(db) // 10] + 8     # room tone + 8 dB counts as silence
    def quiet_runs(i0, i1, q, bridge=0):
        """quiet stretches (40 ms+) in frames [i0, i1) as (first, last) frame; loud blips <= bridge frames are bridged"""
        runs, r0 = [], None
        for i in range(i0, i1 + 1):
            ok = i < i1 and db[i] <= q
            if ok and r0 is None: r0 = i
            if not ok and r0 is not None:
                if i - r0 >= 4:
                    if runs and r0 - runs[-1][1] - 1 <= bridge: runs[-1] = (runs[-1][0], i - 1)
                    else: runs.append((r0, i - 1))
                r0 = None
        return runs
    def snap(t0, t1, after):
        """cut point in [t0, t1]: inside the quiet stretch nearest the kept word (after=True: word is before t0)"""
        i0, i1 = max(0, int(t0 / hop)), min(len(db), int(t1 / hop))
        if i1 - i0 < 2: return None
        runs = quiet_runs(i0, i1, quiet)
        if not runs: return (min(range(i0, i1), key=lambda i: db[i]) + 0.5) * hop
        q0, q1 = runs[0] if after else runs[-1]; q0, q1 = q0 * hop, (q1 + 1) * hop; b = min(a.pad, (q1 - q0) / 2)
        return q0 + b if after else q1 - b
    def pause(e, s):
        """plain pause between kept words (e = end of one, s = start of next): (cut from, cut to) inside real silence, or None"""
        i0, i1 = max(0, int(e / hop)), min(len(db), int(s / hop))
        if i1 - i0 < 4: return None
        q = min(-40, max(quiet, min(db[i0:i1]) + 6))            # louder room: quiet is near the local floor, never speech level
        runs = quiet_runs(i0, i1, q, bridge=12)
        if not runs: return None
        q0, q1 = max(runs, key=lambda r: r[1] - r[0]); q0, q1 = q0 * hop + a.pad, (q1 + 1) * hop - a.pad
        return (q0, q1) if q1 - q0 >= 0.05 else None

    # pad, clamp, and merge anything the padding made touch
    out = []
    for k, (s, e, sd, ed) in enumerate(ranges):
        # next to a dropped word: snap into real silence (env), else the full breath pad where the gap allows
        pd = lambda g: a.pad if g is None else min(a.pad, max(0.0, g) + 0.03)
        s0, e0 = s - pd(sd), e + pd(ed)
        if env and ed is not None: e0 = snap(e, max(e + a.pad, e + ed + 0.03), True) or e0
        if env and sd is not None: s0 = snap(min(s - a.pad, s - sd - 0.03), s, False) or s0
        if env and ed is None and k + 1 < len(ranges): c = pause(e, ranges[k + 1][0]); e0 = c[0] if c else ranges[k + 1][0]
        if env and sd is None and k > 0: c = pause(ranges[k - 1][1], s); s0 = c[1] if c else ranges[k - 1][1]   # None: ranges touch, merge
        s, e = max(lo, s0), min(hi, e0)
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
