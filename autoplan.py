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
  1b. article cards   article.py: Claude finds up to 2 real articles directly about what he says (cached in
                        work/articles.json, passage checked word-for-word) -> split card with highlight, ~6.5 s, on
  2. name labels       first mention of anyone in registry/people.json          ("Sal · Friend since Attica")
  3. place cards       a registry place with a year nearby                        ("📍 ATTICA 2010")
  3. your library     ~/Projects/Reels/_library files whose name (or library.json keys) is said -> B-roll
  3b. archival still  registry place with "archive" -> public-domain Wikimedia photo (after its place card, or instead of stock)
  4. stock B-roll      a registry place/thing with a "stock" query -> Pixabay video (split) or photo (full)
  5. news bars       strongest sentences (STRONG words, numbers) -> red/white TV lower third, <= 1 per 40s
  6. quote card      best strong phrase not used by a news bar -> cream card, Adam in bubble (1 per video)
  7. stat card       most-repeated number + unit ("24 hours") -> huge red number (1 per video)
  7a. Claude's B-roll every project B-roll file still unplaced: Claude looks at it and picks the moment (cached in
                        work/broll_auto.json); no Claude -> spread evenly into free gaps (6 s apart, never the first 3 s)
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
    ap.add_argument("--pool", help="this project's B-roll folder (source/broll): same rules as your library")
    ap.add_argument("--shots", nargs="*", default=[]); ap.add_argument("--no-stock", action="store_true")
    ap.add_argument("--avoid", nargs="*", default=[], help="text that must never appear on a screenshot card (e.g. a wrong date)")
    a = ap.parse_args()
    work = Path(a.work); work.mkdir(parents=True, exist_ok=True)
    ranges = [tuple(map(float, p.split("-"))) for p in a.cuts.split(",")]
    inside = lambda t: any(lo <= t <= hi for lo, hi in ranges)
    out_t = lambda t: sum(max(0.0, min(t, hi) - lo) for lo, hi in ranges)   # source time -> time in the finished video
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
    def ofree(s, e, gap): return all(out_t(e) + gap <= out_t(t0) or out_t(s) >= out_t(t1) + gap for t0, t1 in taken)  # gap as seen (cuts shrink it)
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

    # 1b. article cards: Claude finds real articles about what he says (once per project, work/articles.json, every passage
    #     checked word-for-word); a video whose cuts hold the moment gets a split card for ~6.5 s. On by default, you switch off.
    if os.environ.get("REELSTUDIO_NO_ARTICLES") != "1":
        import article
        segs_all = [s for s in json.load(open(a.transcript))["segments"] if s.get("text", "").strip()]
        seen_ids = set()
        for ar in article.find_articles([(s["start"], s["text"].strip()) for s in segs_all], work.parent / "articles.json"):
            dom = re.sub(r"^www\.", "", urllib.parse.urlparse(ar["url"]).netloc); aid = f"article:{dom}"
            if aid in seen_ids: aid += f"@{ar['t']:.0f}"
            seen_ids.add(aid)
            # the line(s) at t: every segment holding t or starting within 1 s of it (t=85.5 sits on the end of one line
            # AND the start of the next), then the word that names it inside them. No naming word in this video's cuts ->
            # no card here (never fall back to a line start: that put a Sing Sing card 20 s before he said Sing Sing)
            sgs = [x for x in segs_all if x["start"] - 1.0 <= ar["t"] <= x["end"]]
            hi_t = max((x["end"] for x in sgs), default=ar["t"] + 8)
            kw = {norm(x) for x in re.findall(r"[A-Za-z0-9']+", ar.get("about", "")) if len(x) >= 4}
            w0 = min((w for w in words if ar["t"] - 1.0 <= w["start"] <= hi_t and norm(w["word"]) in kw),
                     key=lambda w: abs(w["start"] - ar["t"]), default=None)
            if w0 is None: continue                                                           # not named in this video's cuts
            s = w0["start"]; r_ = next(r for r in ranges if r[0] <= s <= r[1])
            if r_[1] - s < 0.5: s = min((lo for lo, hi in ranges if lo > s), default=s)     # don't open on the last sliver before a cut
            o_e = out_t(s) + 6.5                                                              # 6.5 s on screen, in finished-video time
            e = min([lo + (o_e - out_t(lo)) for lo, hi in ranges if out_t(lo) <= o_e <= out_t(lo) + hi - lo] or [reel_end])
            if out_t(e) - out_t(s) < 4.0: continue                                           # too little room to read it
            cj = work.parent / "articles" / f"{re.sub(r'[^a-z0-9]+', '_', aid.lower())}.json"
            if not cj.exists():
                try: article.make_card(ar["url"], [ar["mark"]], cj.with_suffix(".jpg"))
                except Exception as ex: print(f"[autoplan] article card failed for {ar['url']}: {ex}"); continue
            outlet = article.short_outlet(ar["outlet"])
            add({"id": aid, "type": "broll", "card": str(cj), "kb": "none", "layout": "split", "outlet": outlet, "url": ar["url"],
                 "why": f"{outlet}: {ar['title']} ({ar['url']})"}, s, e)

    # 2. name labels (first mention)
    for p in people:
        hit = find_key(p["keys"])
        if not hit: continue
        s = words[hit[0]]["start"]
        add({"id": f"label:{p['name']}", "type": "label", "name": p["name"], "role": p.get("role", ""),
             "why": f"first mention of {p['name']}"}, s, min(s + 3.2, end_of(s)))

    # 3. your own library (~/Projects/Reels/_library) beats Pixabay: a file plays when its name (or library.json keys) is said
    for lf, keys in library(Path(a.pool) if a.pool else None):
        hit = find_key(keys)
        if not hit: continue
        s = words[hit[0]]["start"]; e = min(s + 3.8, end_of(s))
        item = {"id": f"lib:{lf.name}", "type": "broll", "why": f"'{' '.join(toks[hit[0]:hit[0] + hit[1]])}' -> {'this project' if a.pool and lf.parent == Path(a.pool) else 'your library'} {lf.name}"}
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
        arch = archive(pl["archive"], pl.get("archive_must", pl["name"]), work / "archive", pl.get("archive_file")) if pl.get("archive") else None
        archive_item = lambda s0, e0, f=False: add({"id": f"archive:{pl['name']}", "type": "broll", "image": arch["path"], "label": arch.get("credit") or "ARCHIVE PHOTO",
                                           "kb": next(KB), "why": f"archival: {arch['title']} ({arch['license']})"}, s0, e0, f)
        if pl.get("name") and yr:
            room = arch and free(s, min(s + 6.5, end_of(s)))     # check card + photo together: the photo butts onto its own card
            add({"id": f"place:{pl['name']}", "type": "place", "place": pl["name"], "year": yr,
                 "why": f"{pl['name']} + {yr}"}, s, min(s + 3.0, end_of(s)))
            if room and plan[-1]["on"]: archive_item(s + 3.0, min(s + 6.5, end_of(s)), True)         # the real place, right after its card
        elif arch and free(s, min(s + 3.8, end_of(s))):
            archive_item(s, min(s + 3.8, end_of(s)))                                                  # real history beats stock
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
    pol = polish([x for x in sorted(scored, key=lambda x: -x[0]) if x[0] >= 4][:8], words, work)   # Claude's sharper wording
    for sc, s, hl, raw in sorted(scored, key=lambda x: -x[0]):
        if sc < 4 or len(placed) >= room or any(abs(s - p) < 30 for p in placed): continue
        hl = pol.get(f"{s:.2f}|{raw}", {}).get("headline") or hl
        n0 = len([x for x in plan if x["on"]])
        add({"id": f"news:{s:.0f}", "type": "news", "headline": hl, "kicker": "", "why": f"strong line ({sc}): {hl}"}, s, min(s + 4.5, end_of(s)))
        if len([x for x in plan if x["on"]]) > n0: placed.append(s)

    # 6. quote card: the best strong phrase the news bars didn't use (one per video) -> cream card, Adam in the bubble
    card = lambda extra, s, e: add({"type": "broll", "color": "#F7F1E6", "bubble": "br", "kb": "none", "nocaps": True, **extra}, s, e)
    for sc, s, hl, raw in sorted(scored, key=lambda x: -x[0]):
        if sc < 4 or any(abs(s - p) < 20 for p in placed): continue
        pq = pol.get(f"{s:.2f}|{raw}", {})
        qt = pq.get("quote") or headline(raw, 12); qw = qt.split()
        if len(qw) < 4: continue
        hot = pq.get("hot") or next((w for w in qw if norm(w) in NEWS_STRONG), max(qw, key=len))
        n0 = len([x for x in plan if x["on"]])
        card({"id": f"quote:{s:.0f}", "quote": {"text": qt, "hot": norm(hot)}, "why": f"quote card ({sc}): {qt}"}, s, min(s + 4.5, end_of(s)))
        if len([x for x in plan if x["on"]]) > n0: break

    # 7. stat card: the number + unit said most often ("24 hours", "two hours") -> huge red number (one per video)
    stats = {}
    for i in range(len(toks) - 1):
        n = NUMWORDS.get(toks[i], toks[i] if toks[i].isdigit() and len(toks[i]) < 4 else None)
        if toks[i] in HOMOPHONES and toks[i + 1] in COUNTS: continue   # "painted four people" is usually "painted for people"
        if n and toks[i + 1] in UNITS: stats.setdefault((n, toks[i + 1]), []).append(words[i]["start"])
    for (n, unit), ts in sorted(stats.items(), key=lambda x: -len(x[1])):
        n0 = len([x for x in plan if x["on"]])
        for s in ts:
            card({"id": f"stat:{n} {unit}", "quote": {"num": n, "label": unit}, "why": f"stat card: {n} {unit} (said {len(ts)}x)"}, s, min(s + 3.0, end_of(s)))
            if len([x for x in plan if x["on"]]) > n0: break
            plan.pop()                                  # that moment was busy: try the next mention
        if len([x for x in plan if x["on"]]) > n0: break

    # 7a. every project B-roll file still unplaced (camera names like IMG_6400.JPG never match) gets a moment Claude picks
    #     from the picture itself; no answer / no Claude -> spread evenly into free gaps. You only switch them off.
    #     Runs after the text graphics: those come from his exact words, Claude's picks are a judgement call.
    rest = []                                                           # unplaced files for the even spread (after the cards)
    if a.pool and Path(a.pool).is_dir():
        placed_paths = {x.get("image") or x.get("video") for x in plan if x["on"]}
        left = [f for f in sorted(Path(a.pool).iterdir()) if f.suffix.lower() in VIDS | {".jpg", ".jpeg", ".png"}
                and str(f) not in placed_paths and f"lib:{f.name}" not in off]
        segs = [s for s in json.load(open(a.transcript))["segments"] if s.get("text", "").strip()]
        picks = broll_auto(left, segs, work, skip={f.name for f in left if f"auto:{f.name}" in off})   # switched off: don't ask
        t0 = min(lo for lo, hi in ranges) + 3.0                     # never over the hook (first 3 s)
        ok_at = lambda s: inside(s) and out_t(min(s + 3.8, end_of(s))) - out_t(s) >= 2.5 and s >= t0 and ofree(s, min(s + 3.8, end_of(s)), 1.5)   # 1.5 s of Adam between pictures on screen, no flicker
        def auto_item(f, s, why):
            item = {"id": f"auto:{f.name}", "type": "broll", "why": why}
            if f.suffix.lower() in VIDS: item.update(video=str(f), layout="pip")
            else: item.update(image=str(f), kb=next(KB))
            add(item, s, min(s + 3.8, end_of(s)))
            if item["on"]: plan[:] = [x for x in plan if not (x["id"] == f"lib:{f.name}" and not x["on"] and x["id"] not in off)]  # no twin
        for f in left:
            p_ = picks.get(f.name) or {}
            if not p_.get("moments"): rest.append(f); continue          # no Claude, or nothing he says fits: spread it
            seen = {norm(w) for w in re.split(r"\W+", p_.get("saw", "")) if len(w) >= 4}
            def snap(m):                                                # line start -> the word that matches the picture
                sg = next((x for x in segs if abs(x["start"] - m) < 0.6), None)
                return next((w["start"] for w in (sg or {}).get("words", []) if norm(w["word"]).rstrip("s") in {x.rstrip("s") for x in seen}), m)
            ms = [snap(m) for m in p_["moments"] if inside(m) or inside(snap(m))]
            if not ms: continue                                         # its moments are outside this video's window
            def span(m):                                                # slide only while he's still on that line (or 5 s on / 3 s back)
                sg = next((x for x in segs if x["start"] - 0.6 <= m <= x["end"]), None)
                return (sg["start"] - 1.0, max(sg["end"] - 2.0, m)) if sg else (m - 3.0, m + 5.0)
            nudge = sorted((k * 0.5 for k in range(-60, 61)), key=lambda d: d if d >= 0 else -2 * d)   # closest first, later preferred
            wins = [(m, *span(m)) for m in ms]
            s = next((m + d for d in nudge for m, lo, hi in wins if lo <= m + d <= hi and ok_at(m + d)), None)
            if s is None: rest.append(f); continue                       # its moments are full: the even spread keeps it on
            line = ([x["text"].strip() for x in segs if x["start"] <= s + 1.0] or [""])[-1]
            auto_item(f, s, f"Claude saw {p_.get('saw', 'the picture')} -> '{line[:70]}'")

    # 7b. B-roll Claude couldn't place: spread evenly into the gaps left, never two within 6 s, never the first 3 s
    if rest:
        lo_, hi_ = t0, reel_end - 4.0
        for k, f in enumerate(rest):
            aim = lo_ + (hi_ - lo_) * (k + 0.5) / len(rest)
            near = lambda s: any(abs(out_t(s) - out_t(x["src"][0])) < 6.0 for x in plan if x["on"] and str(x["id"]).startswith("auto:"))
            cand = sorted((aim + d * 0.5 for d in range(-int(hi_ - lo_) * 2, int(hi_ - lo_) * 2 + 1)), key=lambda s: abs(s - aim))
            s = next((c for c in cand if lo_ <= c <= hi_ and ok_at(c) and not near(c)), None)
            if s is not None: auto_item(f, s, f"spread into a free gap ({('switched off, Claude not asked' if f'auto:{f.name}' in off else 'Claude unavailable') if not picks.get(f.name) else 'Claude saw ' + picks[f.name].get('saw', '') + (', its moments were full' if picks[f.name].get('moments') else ', no matching moment')})")

    # 8. emoji: first use of each, at least 5s apart from each other
    used, last = set(), -99.0
    for i, tk in enumerate(toks):
        two = tk + " " + toks[i + 1] if i + 1 < len(toks) else ""
        e_ = emoji[two] if two in emoji else emoji.get(tk)      # a two-word key set to "" blocks it ("heart attack" is no ❤️)
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

    beats = [{k: v for k, v in x.items() if k not in ("on", "why", "outlet", "url")} for x in plan if x["on"]]
    json.dump(beats, open(a.out, "w"), indent=1, ensure_ascii=False)
    if a.plan: json.dump(sorted(plan, key=lambda x: x["src"][0]), open(a.plan, "w"), indent=1, ensure_ascii=False)
    print(f"[autoplan] {len(beats)} beats on, {len(plan) - len(beats)} off -> {a.out}")

NEWS_STRONG = {"miracle", "life", "free", "freedom", "released", "love", "loved", "never", "first", "home", "prison", "parole",
               "amazing", "attica", "years", "decades", "hope", "sun", "died", "dead", "board", "denied", "granted"}
NUMWORDS = {w: str(i) for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}
NUMWORDS.update({"thirty": "30", "forty": "40", "fifty": "50", "hundred": "100", "thousand": "1,000"})
UNITS = {"hours", "years", "days", "months", "weeks", "minutes", "times", "percent", "dollars", "people", "books", "pages"}
HOMOPHONES, COUNTS = {"two", "four", "eight"}, {"people", "books", "pages"}   # to/for/ate + a plain noun: not a stat
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

CLAUDE = Path.home() / ".local" / "bin" / "claude"
POLISH_PROMPT = """You write on-screen text for a talking-head reel by Adam Roberts (formerly incarcerated writer; prison history and
reentry). For each numbered spoken line below, write:
- "headline": a TV-news lower-third headline, 3 to 7 words: state the news itself (what happened, to whom), specific,
  never vague ("Another Friend Denied Parole", not "Word From Inside on Parole"). Strictly true to what he said: never
  add, upgrade or change a fact (a phone call is not a reunion). No em dashes, no clickbait, no exclamation marks, no
  hashtags. Never name or identify anyone still in prison unless the line already names them.
- "quote": the most quotable 5 to 12 words he actually said in that line, lightly cleaned (drop um/like/you know), not
  rewritten.
- "hot": the one word in the quote that carries it (it gets highlighted).
Reply with ONLY JSON: {"1": {"headline": "...", "quote": "...", "hot": "..."}, "2": {...}}
"""

def polish(cands, words, work: Path):
    """Claude rewrites the picked lines as headlines / clean quotes. Cached per line in work/polish.json, so a re-render
    costs nothing; any failure (no Claude, not signed in, timeout) silently falls back to the keyword wording."""
    cache_p = work.parent / "polish.json"; cache = load(cache_p, {})
    todo = [c for c in cands if f"{c[1]:.2f}|{c[3]}" not in cache]
    if todo and CLAUDE.exists() and os.environ.get("REELSTUDIO_NO_CLAUDE") != "1":
        ctx = lambda s: " ".join(w["word"].strip() for w in words if s - 6 <= w["start"] <= s + 12)
        body = "\n".join(f'{n}. Line: "{c[3]}"\n   Context: "{ctx(c[1])}"' for n, c in enumerate(todo, 1))
        try:
            r = subprocess.run([str(CLAUDE), "-p", POLISH_PROMPT + "\n" + body, "--output-format", "text"], capture_output=True,
                               text=True, timeout=150, stdin=subprocess.DEVNULL, cwd=str(Path.home()))
            m = re.search(r"\{.*\}", r.stdout, re.S); got = json.loads(m.group(0)) if m else {}
            for n, c in enumerate(todo, 1):
                g = got.get(str(n)) or {}
                if g.get("headline"):
                    g = {k: re.sub(r"\s*[\u2014\u2013]\s*", ", ", str(v)).strip(' ."') for k, v in g.items()}   # no em dashes, ever
                    cache[f"{c[1]:.2f}|{c[3]}"] = g
            json.dump(cache, open(cache_p, "w"), indent=1, ensure_ascii=False)
            print(f"[autoplan] Claude polished {len(todo)} lines")
        except Exception as ex:
            print(f"[autoplan] Claude polish skipped ({type(ex).__name__}); using keyword wording")
    return cache

BROLL_PROMPT = """You are placing B-roll in a talking-head video by Adam Roberts (formerly incarcerated writer and artist).
Below are his spoken lines with start times in seconds, then numbered picture files from his own phone. Use the Read tool
to look at EVERY picture. For each one, pick the moments (start seconds of the lines above) where the picture best
illustrates what he is saying right then: best first, up to 3, different lines. Only literal matches (a tree when he
talks about the tree, a painting when he talks about painting); if nothing he says fits, give an empty list.
"saw" = what is in the picture, 3 to 8 plain words. Reply with ONLY JSON:
{"1": {"saw": "...", "moments": [12.3, 45.0]}, "2": {...}}
"""

def broll_auto(files, segs, work: Path, skip=()):
    """{file name: {"saw", "moments": [source seconds]}} for project B-roll Claude has looked at. One CLI call for the
    files not yet asked (videos: one frame); cached in work/broll_auto.json by name + mtime so renders don't re-ask.
    Claude off / failing -> {} for those files (the caller spreads them evenly)."""
    cache_p = work.parent / "broll_auto.json"; cache = load(cache_p, {})
    key = lambda f: f"{f.name}|{int(f.stat().st_mtime)}"
    todo = [f for f in files if key(f) not in cache and f.name not in skip]
    if todo and CLAUDE.exists() and os.environ.get("REELSTUDIO_NO_CLAUDE") != "1":
        th = work / "broll_thumbs"; th.mkdir(parents=True, exist_ok=True); pics = []
        for f in todo:                                     # small jpgs: quick for Claude to Read
            t = th / f"{f.name}.{int(f.stat().st_mtime)}.jpg"        # a replaced file gets a fresh thumb
            if not t.exists():
                if f.suffix.lower() in VIDS:
                    subprocess.run(["swift", str(HERE / "grabframes.swift"), str(f), str(th / "_g"), "1.0"], capture_output=True)
                    if (th / "_g" / "frame_0001.jpg").exists(): os.replace(th / "_g" / "frame_0001.jpg", t)
                else: subprocess.run(["sips", "-s", "format", "jpeg", "-Z", "900", str(f), "--out", str(t)], capture_output=True)
            if t.exists(): pics.append((f, t))
        lines = "\n".join(f"[{s['start']:.1f}] {s['text'].strip()}" for s in segs)
        body = "\n".join(f"{n}. {t} ({'video clip, one frame' if f.suffix.lower() in VIDS else 'photo'})" for n, (f, t) in enumerate(pics, 1))
        try:
            r = subprocess.run([str(CLAUDE), "-p", f"{BROLL_PROMPT}\nLINES:\n{lines}\n\nPICTURES:\n{body}", "--allowedTools", "Read",
                                "--output-format", "text"], capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL, cwd=str(th))
            m = re.search(r"\{.*\}", r.stdout, re.S); got = json.loads(m.group(0)) if m else {}
            for n, (f, t) in enumerate(pics, 1):
                g = got.get(str(n))
                if isinstance(g, dict):
                    cache[key(f)] = {"saw": str(g.get("saw", "")).strip()[:80],
                                     "moments": [float(x) for x in g.get("moments", []) if isinstance(x, (int, float))][:3]}
            json.dump(cache, open(cache_p, "w"), indent=1, ensure_ascii=False)
            print(f"[autoplan] Claude placed {sum(key(f) in cache for f, _ in pics)} of {len(pics)} B-roll files")
        except Exception as ex:
            print(f"[autoplan] Claude B-roll pass skipped ({type(ex).__name__}); spreading evenly")
    return {f.name: cache[key(f)] for f in files if key(f) in cache}

def fetch(url, out=None):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh) stage-reel/1.0"})
    data = urllib.request.urlopen(req, timeout=30).read()
    if out: open(out, "wb").write(data)
    return data

KB = itertools.cycle(["in", "left", "out", "right"])   # Ken Burns: photos take turns zooming and panning
LIB = Path.home() / "Projects" / "Reels" / "_library"
VIDS = {".mp4", ".mov", ".m4v"}
LIB_SKIP = {"img", "photo", "video", "clip", "final", "copy", "edit", "the", "and", "with", "from", "for"}

def library(pool=None):
    """[(file, keys)]: keys from library.json {"file.jpg": ["key", ...]} if listed, else the file name's words.
    pool = this project's own B-roll folder; its files come first and follow the same rules."""
    side = load(LIB / "library.json", {}); out = []
    files = (sorted(pool.iterdir()) if pool and pool.is_dir() else []) + (sorted(LIB.iterdir()) if LIB.is_dir() else [])
    for lf in files:
        if lf.suffix.lower() not in VIDS | {".jpg", ".jpeg", ".png"}: continue
        if lf.name in side: keys = side[lf.name]
        else:
            ws = [w for w in re.split(r"[\W_]+", lf.stem.lower()) if w and not w.isdigit() and w not in LIB_SKIP]
            keys = [" ".join(ws)] + [w for w in ws if len(w) >= 4] if ws else []
        if keys: out.append((lf, keys))
    return out

PD_LICENSES = ("public domain", "pd", "cc0", "no restrictions")

def archive(q, must, cache: Path, pin=None):
    """Wikimedia Commons: a public-domain PHOTO whose title names the place (no attribution needed). Cached per query.
    pin = one exact Commons file (registry "archive_file"), which may also be CC BY / CC BY-SA: it then carries a credit.
    -> {"path", "title", "license", "credit"} or None"""
    cache.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"\W+", "_", (pin or q).lower()).strip("_"); meta_p = cache / f"{slug}.json"
    if meta_p.exists():
        m = load(meta_p, None); return m if m and Path(m["path"]).exists() else None
    api = "https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo&iiprop=url|extmetadata|size&iiurlwidth=1080"
    url = api + ("&titles=" + urllib.parse.quote(pin) if pin else "&generator=search&gsrnamespace=6&gsrlimit=30&gsrsearch=" + urllib.parse.quote(q))
    try: pages = json.loads(fetch(url)).get("query", {}).get("pages", {}).values()
    except Exception as ex: print(f"[autoplan] archive search failed: {ex}"); return None
    best = None
    for pg in pages:
        ii = (pg.get("imageinfo") or [{}])[0]; title = pg.get("title", "")
        lic = ii.get("extmetadata", {}).get("LicenseShortName", {}).get("value", "")
        if not re.search(r"\.(jpe?g|png|tiff?)$", title, re.I) or must.lower() not in title.lower(): continue
        if pin and title.replace(" ", "_") != pin.replace(" ", "_"): continue
        ok = lic.lower().startswith(PD_LICENSES) or (pin and re.match(r"cc by(-sa)? \d", lic.lower()))
        if not ok or ii.get("width", 0) < 700: continue
        author = re.sub(r"<[^>]+>", "", ii.get("extmetadata", {}).get("Artist", {}).get("value", "")).split(" from ")[0].strip()
        score = (bool(re.search(r"\b(19|20)\d\d\b", title)), ii.get("width", 0))   # dated photos first, then biggest
        if not best or score > best[0]: best = (score, ii.get("thumburl") or ii.get("url"), title, lic, author)
    if not best: json.dump(None, open(meta_p, "w")); return None
    out = cache / f"{slug}.jpg"
    try: fetch(best[1], out)
    except Exception as ex: print(f"[autoplan] archive download failed: {ex}"); return None
    m = {"path": str(out), "title": best[2].removeprefix("File:"), "license": best[3],
         "credit": "" if best[3].lower().startswith(PD_LICENSES) else f"PHOTO: {best[4]} · {best[3]}"}
    json.dump(m, open(meta_p, "w"), indent=1); return m

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
