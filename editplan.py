#!/usr/bin/env python3
"""
editplan.py — turn a beat sheet written in PHRASES into an edit.json in OUTPUT time
for stagereel.swift --edit. Uses the same cut mapping as makecaptions.py, so reordered or
repeated ranges (cold opens) work.

  python3 editplan.py TRANSCRIPT.json --cuts "a-b,c-d" beats.json --out edit.json

beats.json = list of beats. Every beat names WHEN with phrases from the transcript:
  "from": "pushed the drugs"   -> starts at the first word of that phrase
  "to":   "she didn't die"     -> ends at the LAST word of that phrase
  "occ":  2                     -> which occurrence in the output (default 1; cold opens repeat lines)
  "pad":  [0.1, 0.3]            -> seconds to extend before/after
Types (all other keys pass straight through to stagereel):
  {"type":"broll", "image": "x.jpg" | "color": "#111111", "bubble":"br|bl|none", "label":"FILE PHOTO", "kb":"in|out", "nocaps":false}
  {"type":"punch", "zoom":1.5, "focus":[0.55,0.4]}
  {"type":"counter", "n0":1, "n1":118, "prefix":"DAY ", "label":"THE DA'S CLOCK", "count_to":"took a deal"}
  {"type":"slam", "items":[{"text":"TWO HOURS","at":"two hours"}, ...]}
  {"type":"curtain"}
"""
import argparse, json, re, sys

def norm(t): return re.sub(r"[^a-z0-9']", "", t.lower())

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript"); ap.add_argument("beats")
    ap.add_argument("--cuts", required=True); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    ranges = [tuple(map(float, p.split("-"))) for p in a.cuts.split(",")]
    words = sorted((w for s in json.load(open(a.transcript))["segments"] for w in s.get("words", [])), key=lambda w: w["start"])
    kept, off = [], 0.0
    for lo, hi in ranges:
        for w in words:
            if lo <= w["start"] < hi:
                for i, piece in enumerate(w["word"].split()):  # "a sheet" -> two tokens, same timing
                    kept.append((w["start"] - lo + off, min(w["end"], hi) - lo + off, norm(piece)))
        off += hi - lo
    toks = [k[2] for k in kept]

    def find(phrase, occ=1):
        p = [norm(x) for x in phrase.split()]
        n = 0
        for i in range(len(toks) - len(p) + 1):
            if toks[i:i+len(p)] == p:
                n += 1
                if n == occ: return kept[i][0], kept[i+len(p)-1][1]
        sys.exit(f"editplan: phrase not found (occ {occ}): {phrase!r}")

    def src2out(t):                            # first kept range containing source time t
        o = 0.0
        for lo, hi in ranges:
            if t < lo: return o                # inside a cut-out gap: snap to where the video resumes
            if t <= hi: return o + t - lo
            o += hi - lo
        return o if ranges and t <= ranges[-1][1] + 1.0 else None

    edit = {"punch": [], "broll": [], "graphics": [], "nocaps": []}
    for b in json.load(open(a.beats)):
        b = dict(b); occ = b.pop("occ", 1); pad = b.pop("pad", [0, 0])
        if "src" in b:                         # source-time beat (autoplan.py): map through the cuts
            s0, e0 = b.pop("src"); s, e = src2out(s0), src2out(e0)
            if s is None or e is None: continue     # falls in a cut-out stretch
            b.pop("from", None); b.pop("to", None); s -= pad[0]; e += pad[1]
        else:
            s = find(b.pop("from"), occ)[0] - pad[0]
            e = find(b.pop("to"), occ)[1] + pad[1] if "to" in b else None
        if e is None: b.pop("to", None)
        t = b.pop("type")
        b["start"], b["end"] = round(max(0, s), 3), round(e, 3)
        b.pop("id", None); b.pop("why", None)
        if t == "broll" and "card" in b:          # brollcard.swift output: image + highlighter marks
            card = json.load(open(b.pop("card"))); b["image"] = card["image"]
            groups = sorted({m["group"] for m in card["marks"]})
            # each mark sweeps in at its "at" phrase if given, else marks are spread across the window
            ats = b.pop("mark_at", {})
            lo, hi = b["start"] + 0.6, b["end"] - 0.8
            for gi, g in enumerate(groups):
                ms = [m for m in card["marks"] if m["group"] == g]
                at = ats.get(ms[0]["phrase"])
                t0 = find(at, occ)[0] if at else lo + (hi - lo) * gi / max(1, len(groups))
                for k, m in enumerate(ms): m["start"] = round(t0 + 0.35 * k, 3)
            b["marks"] = card["marks"]
        if t == "counter" and "count_to" in b:
            b["count_end"] = round(find(b.pop("count_to"), occ)[0], 3)
        if t == "slam":
            for it in b["items"]: it["start"] = round(find(it.pop("at"), occ)[0], 3)
        if b.pop("nocaps", t in ("counter", "slam")): edit["nocaps"].append([b["start"], b["end"]])
        if t == "punch": edit["punch"].append(b)
        elif t == "broll": edit["broll"].append(b)
        else: b["type"] = t; edit["graphics"].append(b)
    json.dump(edit, open(a.out, "w"), indent=1)
    print(f"[editplan] {len(edit['punch'])} punches, {len(edit['broll'])} b-roll, {len(edit['graphics'])} graphics -> {a.out}")

if __name__ == "__main__": main()
