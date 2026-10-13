#!/usr/bin/env python3
"""
reelpick.py — pick reel-worthy stretches from a talking-head transcript automatically.

  python3 reelpick.py TRANSCRIPT.json [--n 3] [--min 12] [--max 60]  -> JSON list on stdout:
      [{"name": "reel_sal", "window": "107.1-153.4", "tag": "Sal, Attica", "score": 9.5, "why": "..."}]

How: split the talk into sentences, cut it into "beats" at long pauses (>=1.1s) or topic turns
("so", "and then", "I had", "I met"...), merge beats into 12-60s candidates, score each on what makes a
reel land (registry people/places, emoji-able moments, strong words, a laugh line or quote, a clean ending),
and keep the best N that don't overlap. Tags come from the named people/places in the window.
First choice (Oct 13 2026): Claude reads the numbered sentences and picks whole stand-alone stories (a beginning that
needs no earlier context, a real ending); the keyword scorer is the fallback when Claude is missing or says nothing usable.
"""
import argparse, json, os, re, subprocess
from pathlib import Path

HERE = Path(__file__).parent
TURNS = ("so ", "and so", "and then", "i had", "i met", "i come", "i went", "but then", "after that", "then i",
         "i saw", "so it kind", "i was i saw", "i got a call", "the other day", "this morning", "yesterday")
STRONG = {"miracle", "life", "free", "released", "love", "loved", "never", "first", "home", "prison", "parole",
          "amazing", "awesome", "bullshit", "offended", "sun", "puppy", "attica", "years", "decades", "hope"}

BOOST = []
SENT = (".", "?", "!")
def norm(t): return re.sub(r"[^a-z0-9']", "", t.lower())

def phrase(ws):
    """tag for a reel with no named person/place: its punchiest 2-6 word fragment (strong words win, then shorter)"""
    frags = [f.strip(" ,.?!") for f in re.split(r"[.,!?;]", " ".join(w["word"].strip() for w in ws))]
    frags = [re.sub(r"^(and|so|but|and so|and then)\s+", "", f, flags=re.I) for f in frags if 2 <= len(f.split()) <= 6]
    if not frags: return " ".join(w["word"].strip() for w in ws[:5]).strip(",.")
    f = max(frags, key=lambda f: (len({norm(t) for t in f.split()} & (STRONG | {"living", "dying", "surviving", "tree", "monitor", "chose"})), -len(f.split())))
    return f[0].upper() + f[1:]

CLAUDE = Path.home() / ".local" / "bin" / "claude"
PICK_PROMPT = """You pick reels from a talking-head video by Adam Roberts (formerly incarcerated writer; prison history and
reentry). Below are his sentences, numbered, with start-end seconds. Pick up to {n} reels. Each reel is a run of
consecutive sentences that works as a stand-alone story for someone scrolling who saw nothing else: a beginning that
needs no earlier context (no dangling "that", "this place", "he"), and a real ending (a payoff or landing line, never a
setup cut off before its point). Let each story run its natural length, about 15 to 75 seconds; never pad or trim to a
round number. Reels must not overlap. Fewer strong reels beat more weak ones. "tag": 2 to 5 of his own words from the
reel for a small on-screen label, no em dashes.
Reply with ONLY JSON: [{{"from": 3, "to": 9, "tag": "...", "why": "one short sentence"}}]
"""

def sentences(words):
    """whole sentences (or pause-split pieces) as (start, end, text)"""
    out, cur = [], []
    for i, w in enumerate(words):
        if cur and w["start"] - words[i - 1]["end"] >= 1.1 and not cur[-1]["word"].strip().endswith((",",)) and len(cur) > 2:
            out.append(cur); cur = []
        cur.append(w)
        if w["word"].strip().endswith(SENT): out.append(cur); cur = []
    if cur: out.append(cur)
    return [(c[0]["start"], c[-1]["end"], " ".join(w["word"].strip() for w in c)) for c in out]

def win(words, s, e):
    """source window for a reel: up to 0.3 s of air past its first/last word so deadair's pad isn't clipped, never into a neighbour word"""
    lo = max([s - 0.3] + [w["end"] for w in words if w["end"] <= s]); hi = min([e + 0.3] + [w["start"] for w in words if w["start"] >= e])
    return f"{max(0, min(lo, s)):.2f}-{max(hi, e):.2f}"

def claude_pick(words, n, lo, hi):
    """Claude chooses the stories; returns [] on any failure so the keyword scorer takes over"""
    if not CLAUDE.exists() or os.environ.get("REELSTUDIO_NO_CLAUDE") == "1": return []
    ss = sentences(words)
    body = "\n".join(f"{i}. [{s:.1f}-{e:.1f}] {t}" for i, (s, e, t) in enumerate(ss))
    try:
        r = subprocess.run([str(CLAUDE), "--model", "sonnet", "-p", PICK_PROMPT.format(n=n) + "\n" + body, "--output-format", "text"], capture_output=True,
                           text=True, timeout=180, stdin=subprocess.DEVNULL, cwd=str(Path.home()))
        m = re.search(r"\[.*\]", r.stdout, re.S); got = json.loads(m.group(0)) if m else []
    except Exception: return []
    out = []
    for g in got if isinstance(got, list) else []:
        try: i, j = int(g["from"]), int(g["to"])
        except Exception: continue
        if not (0 <= i <= j < len(ss)): continue
        s, e = ss[i][0], ss[j][1]
        if not (lo <= e - s <= hi) or any(s < o[1] and e > o[0] for o in out): continue
        tag = re.sub(r"\s*[\u2014\u2013]\s*", ", ", str(g.get("tag", ""))).strip(' ."') or ss[i][2][:30]
        out.append((s, e, tag, str(g.get("why", ""))[:120]))
    return sorted(out)[:n]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript"); ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--min", type=float, default=12); ap.add_argument("--max", type=float, default=60)
    ap.add_argument("--boost", nargs="*", default=[], help="phrases that make a window stronger (e.g. names on the screenshots)")
    a = ap.parse_args()
    words = sorted((w for s in json.load(open(a.transcript))["segments"] for w in s.get("words", [])), key=lambda w: w["start"])
    if not words: print("[]"); return
    global BOOST; BOOST = a.boost
    got = claude_pick(words, a.n, a.min, max(a.max, 90))
    if got:
        out = []
        for s, e, tag, why in got:
            tag = tag[0].upper() + tag[1:]
            name = "reel_" + (norm(tag.split()[-1]).replace("'", "") or f"{int(s)}s")      # last word names it: "...busy living" -> reel_living
            while any(o["name"] == name for o in out): name += "2"
            out.append({"name": name, "window": win(words, s, e), "tag": tag, "score": 0, "why": f"{e - s:.0f}s, Claude: {why}"})
        print(json.dumps(out, indent=1, ensure_ascii=False)); return
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
            full = ws[-1]["word"].strip().endswith(SENT)   # a reel ends where a sentence ends ("after decades," is not an ending)
            pi = words.index(ws[0])
            if pi and not words[pi - 1]["word"].strip().endswith(SENT): sc -= 2   # ...and should start where one starts
            cands.append((sc, s, e, tags or [phrase(ws)], " ".join(w["word"].strip() for w in ws[:8]), full))
    if any(c[5] for c in cands): cands = [c for c in cands if c[5]]
    cands = [c[:5] for c in cands]
    picked = []
    for sc, s, e, tags, head in sorted(cands, key=lambda c: -c[0]):
        if len(picked) >= a.n: break
        if any(s < pe and e > ps for _, ps, pe, _, _ in picked): continue
        picked.append((sc, s, e, tags, head))
    out = []
    for sc, s, e, tags, head in sorted(picked, key=lambda c: c[1]):
        tag = ", ".join(tags[:2])
        name = "reel_" + re.sub(r"\W+", "", tags[0].split()[0].lower())
        while any(o["name"] == name for o in out): name += "2"
        out.append({"name": name, "window": win(words, s, e), "tag": tag,
                    "score": round(sc, 1), "why": f"{e - s:.0f}s: {head}..."})
    print(json.dumps(out, indent=1, ensure_ascii=False))

if __name__ == "__main__": main()
