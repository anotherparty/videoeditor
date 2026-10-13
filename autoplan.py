#!/usr/bin/env python3
"""
autoplan.py — plan a reel's on-screen graphics automatically from its transcript (no approval step).

  python3 autoplan.py TRANSCRIPT.json --cuts "a-b,c-d" --work DIR --out beats.json
      [--shots img1 img2 ...] [--off off.json] [--no-stock] [--plan plan.json]

Plans, in priority order (later items never overlap earlier ones):
  0. hand-placed      --manual: B-roll you dragged onto a transcript line in the dashboard (always on)
  1. screenshot cards  (--shots): OCR'd, set on cards, strongest lines highlighted; split screen for text,
                        full screen + bubble for a title/cover image. Anchored at the first mention of a
                        registry person named on the screenshot, else the first "substack/piece/wrote..." word.
  2. name labels       first mention of anyone in registry/people.json          ("Sal · Friend since Attica")
  3. place cards       a registry place with a year nearby                        ("📍 ATTICA 2010")
  3. your library     ~/Projects/Reels/_library files whose name (or library.json keys) is said -> B-roll
  4. stock B-roll      a registry place/thing with a "stock" query -> Pixabay video (split) or photo (full)
  5. news bars       strongest sentences (STRONG words, numbers) -> red/white TV lower third, <= 1 per 40s
  6. quote card      best strong phrase not used by a news bar -> cream card, Adam in bubble (1 per video)
  7. stat card       most-repeated number + unit ("24 hours") -> huge red number (1 per video)
  8. emoji pops        registry/emoji.json words, first use each, spaced out
Writes beats.json (source-time beats for editplan.py) and plan.json (every candidate, with id/why/on —
the dashboard shows it and writes off.json to switch items off). Prints UNKNOWN NAMES for the registry.
"""
import argparse, itertools, json, os, re, subprocess, sys, urllib.parse, urllib.request
from pathlib import Path

HERE = Path(__file__).parent
REG = HERE / "registry"
STRONG = {"miracle", "life", "free", "freedom", "released", "love", "never", "first", "home", "prison",
          "parole", "years", "decades", "hope", "friend", "journalist"}
COMMON_CAPS = {"I", "I'm", "I'll", "I've", "I'd", "God", "OK", "Okay", "So", "And", "But", "The", "A",
               "AI", "TV", "Mr", "Mrs", "Ms", "Dr", "Day", "Quill", "DayQuil"}

def norm(t): return re.sub(r"[^a-z0-9']", "", t.lower())

def load(p, default):
    try: return json.load(open(p))
    except Exception: return default

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript"); ap.add_argument("--cuts", required=True)
    ap.add_argument("--work", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--plan"); ap.add_argument("--off"); ap.add_argument("--manual", help="hand-placed B-roll [{path, start, end}] (source time)")
    ap.add_argument("--moves", help="timeline drags {id: [start, end]} (source time) from the dashboard")
    ap.add_argument("--shots", nargs="*", default=[]); ap.add_argument("--no-stock", action="store_true")
    ap.add_argument("--avoid", nargs="*", default=[], help="text that must never appear on a screenshot card (e.g. a wrong date)")
    a = ap.parse_args()
    work = Path(a.work); work.mkdir(parents=True, exist_ok=True)
    ranges = [tuple(map(float, p.split("-"))) for p in a.cuts.split(",")]
    inside = lambda t: any(lo <= t <= hi for lo, hi in ranges)
    reel_end = max(hi for lo, hi in ranges)
    end_of = lambda t: reel_end
    words = sorted((w for s in json.load(open(a.transcript))["segments"] for w in s.get("words", [])), key=lambda w: w["start"])
    words = [w for w in words if inside(w["start"])]
    toks = [norm(w["word"]) for w in words]
    people, places, emoji = load(REG / "people.json", []), load(REG / "places.json", []), load(REG / "emoji.json", {})
    ignore = set(load(REG / "ignore.json", []))         # capitalized words that aren't people/places (brands, apps)
    off = set(load(a.off, [])) if a.off else set()

    def find_key(keys, start=0):
        """first token index where any multi-word key matches -> (index, ntoks)"""
        best = None
        for k in keys:
            kt = [norm(x) for x in k.split()]
            for i in range(start, len(toks) - len(kt) + 1):
                if toks[i:i + len(kt)] == kt:
                    if best is None or i < best[0] or (i == best[0] and len(kt) > best[1]): best = (i, len(kt))
                    break
        return best

    moves = {k: tuple(v) for k, v in (load(a.moves, {}) if a.moves else {}).items()}
    plan, taken = [], list(moves.values())      # taken = (start, end) source-time intervals; your moved spans are reserved
    def free(s, e, gap=0.4): return all(e + gap <= t0 or s >= t1 + gap for t0, t1 in taken)
    def add(item, s, e, force=False):
        if item["id"] in moves:           # you dragged it on the timeline: your span wins, and it's always on
            s, e = moves[item["id"]]; force = True; item["moved"] = True; item["why"] += " (moved by you)"
            taken[:] = [x for x in taken if x != tuple(moves[item["id"]])]
        item.update(src=[round(s, 2), round(e, 2)])
        item["on"] = item["id"] not in off and (force or free(s, e))
        if not item["on"] and item["id"] not in off: item["why"] += " (skipped: overlaps)"
        plan.append(item)
        if item["on"]: taken.append((s, e))

    # 0. hand-placed B-roll (dragged onto a transcript line) beats everything automatic
    for k, m in enumerate(load(a.manual, []) if a.manual else []):
        if not inside(m["start"]) or not Path(m["path"]).exists(): continue
        s, e = m["start"], min(max(m["end"], m["start"] + 2.5), end_of(m["start"]))
        item = {"id": f"hand:{k}:{Path(m['path']).name}", "type": "broll", "why": f"you placed {Path(m['path']).name} here"}
        if Path(m["path"]).suffix.lower() in VIDS: item.update(video=m["path"], layout="pip")
        else: item.update(image=m["path"], kb=next(KB))
        add(item, s, e, force=True)

    # 1. screenshots
    if a.shots:
        ocr = json.loads(subprocess.run(["swift", str(HERE / "ocr.swift"), *a.shots], capture_output=True, text=True).stdout or "{}")
        lines_of = lambda p: [l["text"] for l in ocr.get(p, {}).get("lines", [])]
        cover = [p for p in a.shots if len(lines_of(p)) <= 6][:1]          # a title/cover image goes first
        shots = cover + [p for p in a.shots if p not in cover]
        names = [k for p in people for k in p["keys"]]
        alltext = " ".join(norm(x) for p in shots for x in " ".join(lines_of(p)).split())
        on_shot = [k for k in names if all(norm(x) in alltext.split() for x in k.split())]
        hit = find_key(on_shot) if on_shot else None
        if hit is None: hit = find_key(["substack", "published", "piece", "article", "wrote", "letter", "essay", "post"])
        if hit is None: shots = []                  # this window never gets to the screenshots' topic
        t = words[hit[0]]["start"] if hit else 0
        for n, p in enumerate(shots):
            info = ocr.get(p, {}); boxes = info.get("lines", []); lines = [l["text"] for l in boxes]
            iw, ih = (info.get("size") or [1, 1])
            is_text = len(lines) > 6
            dur = 6.5 if is_text else 4.0
            s, e = t, min(t + dur, end_of(t))
            if e - s < 2.0: break
            marks = []
            if is_text:
                scored = []
                for li, ln in enumerate(lines):
                    frags = [f.strip(" “”\"") for f in re.split(r"[,.;:]", ln) if len(f.strip()) > 8]
                    for f in frags:
                        fw = {norm(x) for x in f.split()}
                        sc = 3 * ("adam" in fw) + 2 * any(norm(k) in fw for k in names) + len(fw & STRONG)
                        if sc: scored.append((sc, f, li))
                # crop to the passage that holds the most highlight weight, so text stays readable in the top half
                win = iw / 1.55 / ih                                      # crop height (0-1) matching the split card
                # lines that must never show (--avoid): the crop may not reach them
                bad = [l["y0"] for l in boxes if any(a_.lower() in l["text"].lower() for a_ in a.avoid)]
                # also drop the line just above (its sentence runs into the forbidden one, e.g. "I wrote to Adam in")
                bad = sorted({max([l["y0"] for l in boxes if l["y0"] < b_] or [b_]) for b_ in bad} | set(bad))
                def clip(y0, y1):
                    for b in bad:
                        if y0 <= b < y1: y1 = b - 0.004                   # stop just above the forbidden line
                    return y0, y1
                best, crop = -1, clip(0.0, min(1.0, win))
                for _, _, li in scored:
                    y0 = max(0.0, min(1.0 - win, boxes[li]["y0"] - 0.02))
                    if any(y0 <= b <= boxes[li]["y0"] for b in bad): continue    # a forbidden line sits above this start
                    c0, c1 = clip(y0, y0 + win)
                    if c1 - c0 < 0.04: continue
                    w_ = sum(sc for sc, _, lj in scored if boxes[lj]["y0"] >= c0 and boxes[lj]["y1"] <= c1)
                    if w_ > best: best, crop = w_, (c0, c1)
                seen = set()
                for sc, f, li in sorted(scored, key=lambda x: -x[0]):
                    if boxes[li]["y0"] >= crop[0] and boxes[li]["y1"] <= crop[1] and f not in seen and len(marks) < 3:
                        marks.append(f); seen.add(f)
            card = work / f"shot{n}.jpg"
            cmd = ["swift", str(HERE / "brollcard.swift"), "--in", p, "--out", str(card), "--bg", "18191B" if is_text else "F7F7F6"]
            if is_text: cmd += ["--size", "split", "--crop", f"0,{int(crop[0] * ih)},{iw},{int((crop[1] - crop[0]) * ih)}"]
            for m in marks: cmd += ["--mark", m]
            subprocess.run(cmd, capture_output=True, text=True)
            add({"id": f"shot:{Path(p).name}", "type": "broll", "card": str(card.with_suffix(".json")),
                 "kb": "none" if is_text else "in", "layout": "split" if is_text else "full",
                 "why": f"screenshot {Path(p).name}" + (f", highlights: {marks}" if marks else "")}, s, e, force=True)
            t = e

    # 2. name labels (first mention)
    for p in people:
        hit = find_key(p["keys"])
        if not hit: continue
        s = words[hit[0]]["start"]
        add({"id": f"label:{p['name']}", "type": "label", "name": p["name"], "role": p.get("role", ""),
             "why": f"first mention of {p['name']}"}, s, min(s + 3.2, end_of(s)))

    # 3. your own library (~/Projects/Reels/_library) beats Pixabay: a file plays when its name (or library.json keys) is said
    for lf, keys in library():
        hit = find_key(keys)
        if not hit: continue
        s = words[hit[0]]["start"]; e = min(s + 3.8, end_of(s))
        item = {"id": f"lib:{lf.name}", "type": "broll", "why": f"'{' '.join(toks[hit[0]:hit[0] + hit[1]])}' -> your library {lf.name}"}
        if lf.suffix.lower() in VIDS: item.update(video=str(lf), layout="pip")    # your clip full screen, you in a framed corner box
        else: item.update(image=str(lf), kb=next(KB))
        add(item, s, e)

    # 4/5. places: year nearby -> place card; else stock query -> B-roll
    for pl in places:
        hit = find_key(pl["keys"])
        if not hit: continue
        i = hit[0]; s = words[i]["start"]
        yr = next((re.sub(r"\D", "", words[j]["word"]) for j in range(max(0, i - 8), min(len(words), i + 9))
                   if re.fullmatch(r"(19[5-9]\d|20[0-3]\d)", re.sub(r"\D", "", words[j]["word"]))), "")
        if pl.get("name") and yr:
            add({"id": f"place:{pl['name']}", "type": "place", "place": pl["name"], "year": yr,
                 "why": f"{pl['name']} + {yr}"}, s, min(s + 3.0, end_of(s)))
        elif pl.get("stock") and not a.no_stock:
            e = min(s + 3.8, end_of(s))
            if not free(s, e): continue
            media = stock(pl["stock"], work / "stock", e - s)
            if not media: continue
            item = {"id": f"stock:{pl['stock']}", "why": f"'{' '.join(pl['keys'][:1])}' -> Pixabay '{pl['stock']}'", "type": "broll"}
            if media.endswith(".mp4"): item.update(video=media)
            else: item.update(image=media, label="FILE PHOTO", kb=next(KB))
            add(item, s, e)
        elif pl.get("name"):
            add({"id": f"place:{pl['name']}", "type": "place", "place": pl["name"], "year": "",
                 "why": f"mention of {pl['name']}"}, s, min(s + 2.6, end_of(s)))

    # 5. news lower thirds: only the strongest phrases (clause-sized, like a headline), at most one per ~40s
    names = {norm(k) for x in people + places for k in x["keys"] for k in k.split()}
    clauses, cur = [], []
    for i, w in enumerate(words):
        cur.append(i)
        if re.search(r"[.,?!;:]$", w["word"].strip()) or i == len(words) - 1: clauses.append(cur); cur = []
    scored = []
    for k, ix in enumerate(clauses):
        if len(ix) < 6 and k + 1 < len(clauses): ix = ix + clauses[k + 1]          # a short clause borrows the next one
        hl = headline(" ".join(words[i]["word"].strip() for i in ix))
        hw = [norm(w) for w in hl.split()]
        if len(hw) < 4: continue
        sc = 2 * sum(w in NEWS_STRONG for w in hw) + sum(w in names for w in hw) + 2 * sum(bool(re.fullmatch(r"(19|20)\d\d", w)) for w in hw) \
             + sum(w in NEWS_TURN for w in hw)
        scored.append((sc, words[ix[0]]["start"], hl, " ".join(words[i]["word"].strip() for i in ix)))
    span = sum(hi - lo for lo, hi in ranges); room = max(1, int(span // 40)); placed = []
    for sc, s, hl, _ in sorted(scored, key=lambda x: -x[0]):
        if sc < 4 or len(placed) >= room or any(abs(s - p) < 30 for p in placed): continue
        n0 = len([x for x in plan if x["on"]])
        add({"id": f"news:{s:.0f}", "type": "news", "headline": hl, "kicker": "", "why": f"strong line ({sc}): {hl}"}, s, min(s + 4.5, end_of(s)))
        if len([x for x in plan if x["on"]]) > n0: placed.append(s)

    # 6. quote card: the best strong phrase the news bars didn't use (one per video) -> cream card, Adam in the bubble
    card = lambda extra, s, e: add({"type": "broll", "color": "#F7F1E6", "bubble": "br", "kb": "none", "nocaps": True, **extra}, s, e)
    for sc, s, hl, raw in sorted(scored, key=lambda x: -x[0]):
        if sc < 4 or any(abs(s - p) < 20 for p in placed): continue
        qt = headline(raw, 12); qw = qt.split()
        if len(qw) < 4: continue
        hot = next((w for w in qw if norm(w) in NEWS_STRONG), max(qw, key=len))
        n0 = len([x for x in plan if x["on"]])
        card({"id": f"quote:{s:.0f}", "quote": {"text": qt, "hot": norm(hot)}, "why": f"quote card ({sc}): {qt}"}, s, min(s + 4.5, end_of(s)))
        if len([x for x in plan if x["on"]]) > n0: break

    # 7. stat card: the number + unit said most often ("24 hours", "two hours") -> huge red number (one per video)
    stats = {}
    for i in range(len(toks) - 1):
        n = NUMWORDS.get(toks[i], toks[i] if toks[i].isdigit() and len(toks[i]) < 4 else None)
        if n and toks[i + 1] in UNITS: stats.setdefault((n, toks[i + 1]), []).append(words[i]["start"])
    for (n, unit), ts in sorted(stats.items(), key=lambda x: -len(x[1])):
        n0 = len([x for x in plan if x["on"]])
        for s in ts:
            card({"id": f"stat:{n} {unit}", "quote": {"num": n, "label": unit}, "why": f"stat card: {n} {unit} (said {len(ts)}x)"}, s, min(s + 3.0, end_of(s)))
            if len([x for x in plan if x["on"]]) > n0: break
            plan.pop()                                  # that moment was busy: try the next mention
        if len([x for x in plan if x["on"]]) > n0: break

    # 8. emoji: first use of each, at least 5s apart from each other
    used, last = set(), -99.0
    for i, tk in enumerate(toks):
        two = tk + " " + toks[i + 1] if i + 1 < len(toks) else ""
        e_ = emoji.get(two) or emoji.get(tk)
        if not e_ or e_ in used: continue
        s = words[i]["start"]
        if s - last < 5.0: continue
        n0 = len([x for x in plan if x["on"]])
        add({"id": f"emoji:{tk}@{s:.0f}", "type": "emoji", "emoji": e_, "why": f"'{words[i]['word'].strip()}'"}, s, min(s + 1.8, end_of(s)))
        if len([x for x in plan if x["on"]]) > n0: used.add(e_); last = s

    # unknown names for the registry
    known = {norm(k) for p in people for k in p["keys"] for k in k.split()} | {norm(k) for p in places for k in p["keys"] for k in k.split()}
    unk = sorted({w["word"].strip(" ,.?!") for k, w in enumerate(words) if k and w["word"].strip()[:1].isupper()
                  and not words[k - 1]["word"].strip().endswith((".", "?", "!"))
                  and w["word"].strip(" ,.?!") not in COMMON_CAPS | ignore and norm(w["word"]) not in known})
    if unk: print("UNKNOWN NAMES (add to registry/people.json or places.json):", ", ".join(unk))

    beats = [{k: v for k, v in x.items() if k not in ("on", "why")} for x in plan if x["on"]]
    json.dump(beats, open(a.out, "w"), indent=1, ensure_ascii=False)
    if a.plan: json.dump(sorted(plan, key=lambda x: x["src"][0]), open(a.plan, "w"), indent=1, ensure_ascii=False)
    print(f"[autoplan] {len(beats)} beats on, {len(plan) - len(beats)} off -> {a.out}")

NEWS_STRONG = {"miracle", "life", "free", "freedom", "released", "love", "loved", "never", "first", "home", "prison", "parole",
               "amazing", "attica", "years", "decades", "hope", "sun", "died", "dead", "board", "denied", "granted"}
NUMWORDS = {w: str(i) for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}
NUMWORDS.update({"thirty": "30", "forty": "40", "fifty": "50", "hundred": "100", "thousand": "1,000"})
UNITS = {"hours", "years", "days", "months", "weeks", "minutes", "times", "percent", "dollars", "people", "books", "pages"}
NEWS_TURN = {"didn't", "never", "finally", "won't", "can't", "since", "still", "first", "last"}
LEAD = r"^((from|inside|that|then|which|who|and|so|but|because|where|when)\s+)+"
TRAIL = r"(\s+(and|so|but|that|the|a|to|of|with|they're|he's|she's|it's|i'm|was|is|in|on|my|his|her))+$"
FILLER = r"\b(you know|i mean|kind of|sort of|like|um+|uh+|really|actually|just|basically|literally)\b,?"
def headline(s, maxw=8):
    """spoken sentence -> short news headline: drop filler and lead-ins, keep the strongest stretch of <= maxw words"""
    s = re.sub(FILLER, " ", s, flags=re.I); s = re.sub(r"^(\W*(so|and|but|well|now|okay|ok|yeah)\b,?\s*)+", "", s.strip(), flags=re.I)
    ws = [w for w in re.sub(r"[.?!,;:]+$", "", re.sub(r"\s+", " ", s)).split(" ") if w]
    if len(ws) <= maxw: return re.sub(LEAD, "", re.sub(TRAIL, "", " ".join(ws).strip(" ,"), flags=re.I), flags=re.I)
    best = max(range(len(ws) - maxw + 1), key=lambda i: sum(norm(w) in NEWS_STRONG or any(c.isdigit() for c in w) for w in ws[i:i + maxw]))
    return re.sub(LEAD, "", re.sub(TRAIL, "", " ".join(ws[best:best + maxw]).strip(" ,"), flags=re.I), flags=re.I)

def fetch(url, out=None):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh) stage-reel/1.0"})
    data = urllib.request.urlopen(req, timeout=30).read()
    if out: open(out, "wb").write(data)
    return data

KB = itertools.cycle(["in", "left", "out", "right"])   # Ken Burns: photos take turns zooming and panning
LIB = Path.home() / "Projects" / "Reels" / "_library"
VIDS = {".mp4", ".mov", ".m4v"}
LIB_SKIP = {"img", "photo", "video", "clip", "final", "copy", "edit", "the", "and", "with", "from", "for"}

def library():
    """[(file, keys)]: keys from library.json {"file.jpg": ["key", ...]} if listed, else the file name's words"""
    if not LIB.is_dir(): return []
    side = load(LIB / "library.json", {}); out = []
    for lf in sorted(LIB.iterdir()):
        if lf.suffix.lower() not in VIDS | {".jpg", ".jpeg", ".png"}: continue
        if lf.name in side: keys = side[lf.name]
        else:
            ws = [w for w in re.split(r"[\W_]+", lf.stem.lower()) if w and not w.isdigit() and w not in LIB_SKIP]
            keys = [" ".join(ws)] + [w for w in ws if len(w) >= 4] if ws else []
        if keys: out.append((lf, keys))
    return out

def stock(q, cache: Path, need: float):
    """Pixabay: a video clip >= need seconds (preferred), else a photo. Cached by query."""
    cache.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"\W+", "_", q.lower()).strip("_")
    for ext in (".mp4", ".jpg"):
        if (cache / (slug + ext)).exists(): return str(cache / (slug + ext))
    try: key = open(os.path.expanduser("~/.config/another-party/pixabay_key")).read().strip()
    except Exception: return None
    qs = urllib.parse.quote_plus(q)
    try:
        d = json.loads(fetch(f"https://pixabay.com/api/videos/?key={key}&q={qs}&safesearch=true&per_page=10"))
        for h in d.get("hits", []):
            if h.get("duration", 0) >= need and h["videos"].get("medium", {}).get("url"):
                out = cache / (slug + ".mp4"); fetch(h["videos"]["medium"]["url"], out); return str(out)
        d = json.loads(fetch(f"https://pixabay.com/api/?key={key}&q={qs}&image_type=photo&orientation=vertical&safesearch=true&per_page=5"))
        if d.get("hits"):
            out = cache / (slug + ".jpg"); fetch(d["hits"][0]["largeImageURL"], out); return str(out)
    except Exception as ex:
        print(f"[autoplan] stock fetch failed for '{q}': {ex}", file=sys.stderr)
    return None

if __name__ == "__main__": main()
