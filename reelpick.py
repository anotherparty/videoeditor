#!/usr/bin/env python3
"""
reelpick.py — pick reel-worthy stretches from a talking-head transcript automatically.

  python3 reelpick.py TRANSCRIPT.json [--n 3] [--min 12] [--max 60]  -> JSON list on stdout:
      [{"name": "reel_sal", "window": "107.1-153.4", "tag": "Sal, Attica", "score": 9.5, "why": "..."}]

How: split the talk into sentences, cut it into "beats" at long pauses (>=1.1s) or topic turns
("so", "and then", "I had", "I met"...), merge beats into 12-60s candidates, score each on what makes a
reel land (registry people/places, emoji-able moments, strong words, a laugh line or quote, a clean ending),
and keep the best N that don't overlap. Tags come from the named people/places in the window.
"""
import argparse, json, re
from pathlib import Path

HERE = Path(__file__).parent
TURNS = ("so ", "and so", "and then", "i had", "i met", "i come", "i went", "but then", "after that", "then i",
         "i saw", "so it kind", "i was i saw", "i got a call", "the other day", "this morning", "yesterday")
STRONG = {"miracle", "life", "free", "released", "love", "loved", "never", "first", "home", "prison", "parole",
          "amazing", "awesome", "bullshit", "offended", "sun", "puppy", "attica", "years", "decades", "hope"}

BOOST = []
def norm(t): return re.sub(r"[^a-z0-9']", "", t.lower())

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript"); ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--min", type=float, default=12); ap.add_argument("--max", type=float, default=60)
    ap.add_argument("--boost", nargs="*", default=[], help="phrases that make a window stronger (e.g. names on the screenshots)")
    a = ap.parse_args()
    words = sorted((w for s in json.load(open(a.transcript))["segments"] for w in s.get("words", [])), key=lambda w: w["start"])
    if not words: print("[]"); return
    global BOOST; BOOST = a.boost
    reg = lambda f, d: json.load(open(HERE / "registry" / f)) if (HERE / "registry" / f).exists() else d
    people, places, emoji = reg("people.json", []), reg("places.json", []), reg("emoji.json", {})

    # beats: split the word stream at long pauses, at sentence ends followed by a turn phrase, or at a
    # turn phrase after a comma ("..., and then I was, I saw at therapy") — whisper runs sentences together
    toks_all = [norm(w["word"]) for w in words]
    cuts = [0]
    for i in range(1, len(words)):
        gap = words[i]["start"] - words[i - 1]["end"]
        prev = words[i - 1]["word"].strip()
        ahead = " ".join(toks_all[i:i + 3]) + " "
        turn = ahead.startswith(TURNS)
        if gap >= 1.1 or (turn and (prev.endswith((".", "?", "!", ",")) or gap >= 0.4)):
            if words[i]["start"] - words[cuts[-1]]["start"] >= 4.0: cuts.append(i)
    cuts.append(len(words))
    spans = [(words[a]["start"], words[b - 1]["end"], words[a:b]) for a, b in zip(cuts, cuts[1:])]

    def score(ws):
        toks = [norm(w["word"]) for w in ws]; txt = " " + " ".join(toks) + " "
        names = [p["name"] for p in people if any(f" {' '.join(norm(x) for x in k.split())} " in txt for k in p["keys"])]
        plc = [p["name"] or p["keys"][0] for p in places if any(f" {' '.join(norm(x) for x in k.split())} " in txt for k in p["keys"])]
        emo = len({emoji[t] for t in toks if t in emoji})
        st = len(set(toks) & STRONG)
        quote = 1 if re.search(r"\b(he|she|they|guy|guard) (was|said) like\b", txt) else 0
        boost = sum(4 for b in BOOST if f" {' '.join(norm(x) for x in b.split())} " in txt)
        sc = 2 * len(names) + 1.5 * len(plc) + emo + st + 2 * quote + boost
        return sc, names + [p for p in plc if p not in names]

    cands = []
    for i in range(len(spans)):
        for j in range(i, len(spans)):
            s, e = spans[i][0], spans[j][1]
            if e - s > a.max: break
            if e - s < a.min: continue
            ws = [w for k in range(i, j + 1) for w in spans[k][2]]
            sc, tags = score(ws)
            sc -= 0.8 * (j - i)                        # each extra beat must earn its place
            people_here = [t for t in tags if any(t == p["name"] for p in people)]
            if len(people_here) > 1: sc -= 3                # two different people = two stories
            if j == len(spans) - 1 or norm(spans[j][2][-1]["word"]) in ("peace", "awesome", "amazing"): sc += 1.5  # lands on a closer
            sc = sc / ((e - s) / 30) ** 0.7            # density matters, but longer stories can still win
            cands.append((sc, s, e, tags, " ".join(w["word"].strip() for w in ws[:8])))
    picked = []
    for sc, s, e, tags, head in sorted(cands, key=lambda c: -c[0]):
        if len(picked) >= a.n: break
        if any(s < pe and e > ps for _, ps, pe, _, _ in picked): continue
        picked.append((sc, s, e, tags, head))
    out = []
    for sc, s, e, tags, head in sorted(picked, key=lambda c: c[1]):
        tag = ", ".join(tags[:2]) if tags else " ".join(head.split()[:5]).strip(",.")
        name = "reel_" + (re.sub(r"\W+", "", tags[0].split()[0].lower()) if tags else f"{int(s)}s")
        while any(o["name"] == name for o in out): name += "2"
        out.append({"name": name, "window": f"{max(0, s - 0.1):.1f}-{e + 0.05:.2f}", "tag": tag,
                    "score": round(sc, 1), "why": f"{e - s:.0f}s: {head}..."})
    print(json.dumps(out, indent=1, ensure_ascii=False))

if __name__ == "__main__": main()
