#!/usr/bin/env python3
"""
article.py — turn a web article into a B-roll card with a highlighter sweep (like the Phil Smith screenshots,
but no screenshot needed).

  python3 article.py URL --mark "exact words from the article" --out DIR/art0.jpg

Steps: fetch the page -> pull outlet, headline, byline, date and paragraphs -> find the paragraph holding the
mark (must be word-for-word in the article, else it stops) -> articlecard.swift lays out a clean news page
(outlet, headline, byline, that paragraph) -> brollcard.swift adds the highlighter marks (split-screen card).
Prints the card .json path (use it as "card" in beats.json), or exits 1 with the reason.

find_articles() is the "I find them myself" part: Claude reads the transcript, searches the web and proposes up to
2 articles + a passage; each passage is then checked word-for-word against the fetched page (no invented quotes).
autoplan.py calls it once per project (cached in work/articles.json); the cards arrive switched OFF until Adam approves.
"""
import argparse, json, os, re, subprocess, sys, urllib.request
from pathlib import Path
from bs4 import BeautifulSoup

HERE = Path(__file__).parent
CLAUDE = Path.home() / ".local/bin/claude"
FIND_PROMPT = """You find news articles to show as B-roll in a short vertical video by Adam Roberts, a formerly
incarcerated writer. Below is what he says, with timestamps in seconds.
Pick AT MOST 2 moments where a real published article from a reputable source (news outlet, public radio,
nonprofit newsroom) directly backs up or gives context to what he says: a public fact, a prison, a law, a
public event, a statistic. Never pick anything about the private people he mentions (friends, family, people
still inside, their cases). If nothing fits, return an empty list. That is a fine answer.
For each pick: search the web, open the article, and copy one short passage (6 to 18 words) from the article
BODY, not the headline, EXACTLY as written, character for character. Prefer free pages without a paywall.
Reply with JSON only: {"articles": [{"t": <seconds where he says it>, "said": "<his words>", "url": "<article url>", "mark": "<exact passage>"}]}
"""
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
squash = lambda s: re.sub(r"\s+", " ", s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')).strip()

def fetch(url):
    """-> {outlet, title, byline, date, paras} (paras = body paragraphs, cleaned)"""
    html = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=20).read().decode("utf-8", "replace")
    s = BeautifulSoup(html, "html.parser")
    meta = lambda *ks: next((m.get("content", "").strip() for k in ks for m in s.find_all("meta", attrs={"property": k}) + s.find_all("meta", attrs={"name": k}) if m.get("content")), "")
    title = meta("og:title", "twitter:title") or (s.h1.get_text(" ", strip=True) if s.h1 else "")
    outlet = meta("og:site_name") or re.sub(r"^www\.", "", urllib.request.urlparse(url).netloc)
    title = re.sub(rf"\s*[|\-–—]\s*{re.escape(outlet)}\s*$", "", title, flags=re.I)       # "Headline | Outlet" -> "Headline"
    for t in s(["script", "style", "nav", "header", "footer", "aside", "form", "figure"]): t.decompose()
    body = s.find("article") or s.find("main") or s.body or s
    paras = [squash(p.get_text(" ", strip=True)) for p in body.find_all("p")]
    paras = [p for p in paras if len(p) > 60 and not re.search(r"cookie|subscribe|newsletter|all rights reserved", p, re.I)]
    date = meta("article:published_time", "date", "pubdate")[:10]
    by = meta("author", "article:author")
    if by.startswith("http"): by = by.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").title()     # ".../people/dave-davies" -> "Dave Davies"
    return {"outlet": outlet, "title": squash(title), "byline": by, "date": date, "paras": paras, "url": url}

def find_para(paras, mark):
    k = squash(mark).lower()
    return next((i for i, p in enumerate(paras) if k in p.lower()), None)

def make_card(url, marks, out: Path, art=None):
    """-> card .json path; raises ValueError with the reason"""
    out.parent.mkdir(parents=True, exist_ok=True)
    art = art or fetch(url)
    i = find_para(art["paras"], marks[0])
    if i is None: raise ValueError(f"'{marks[0]}' is not word-for-word in {url} ({len(art['paras'])} paragraphs read)")
    page = dict(art, paras=art["paras"][i:i + 2], lead=i > 0)       # lead: the passage starts mid-article -> "…"
    pj = out.with_name(out.stem + "_page.json"); pj.write_text(json.dumps(page, indent=1))
    png = out.with_name(out.stem + "_page.png")
    r = subprocess.run(["swift", str(HERE / "articlecard.swift"), str(pj), str(png)], capture_output=True, text=True)
    if not png.exists(): raise ValueError("page render failed: " + r.stderr[-400:])
    cmd = ["swift", str(HERE / "brollcard.swift"), "--in", str(png), "--out", str(out), "--bg", "FFFFFF", "--size", "split"]
    for m in marks: cmd += ["--mark", squash(m)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    card = out.with_suffix(".json")
    if not card.exists(): raise ValueError("card failed: " + r.stderr[-400:])
    if not json.load(open(card)).get("marks"): print(f"[article] warning: highlight not found on the card", file=sys.stderr)
    return card

def find_articles(lines, cache_p: Path):
    """lines = [(start_seconds, text)] for the whole transcript -> [{t, said, url, mark, outlet, title}] (verified).
    Cached in cache_p; any failure (no Claude, timeout, nothing verified) -> [] and the reel renders without articles."""
    if cache_p.exists(): return json.load(open(cache_p))
    if not CLAUDE.exists() or os.environ.get("REELSTUDIO_NO_CLAUDE") == "1": return []
    body = "\n".join(f"[{s:.1f}] {tx}" for s, tx in lines)[:12000]
    try:
        r = subprocess.run([str(CLAUDE), "-p", FIND_PROMPT + "\n# What Adam says\n" + body, "--output-format", "text",
                            "--allowedTools", "WebSearch", "WebFetch"], capture_output=True, text=True, timeout=420,
                           stdin=subprocess.DEVNULL, cwd=str(Path.home()))
        m = re.search(r"\{.*\}", r.stdout, re.S); picks = json.loads(m.group(0)).get("articles", []) if m else []
    except Exception as ex:
        print(f"[article] finder skipped ({type(ex).__name__})"); return []
    found = []
    for pk in picks[:2]:
        try:
            art = fetch(pk["url"])
            if find_para(art["paras"], pk["mark"]) is None: print(f"[article] dropped {pk['url']}: passage not word-for-word"); continue
            found.append({"t": float(pk["t"]), "said": pk.get("said", ""), "url": pk["url"], "mark": squash(pk["mark"]),
                          "outlet": art["outlet"], "title": art["title"]})
        except Exception as ex: print(f"[article] dropped {pk.get('url')}: {type(ex).__name__}")
    cache_p.write_text(json.dumps(found, indent=1, ensure_ascii=False)); print(f"[article] {len(found)} of {len(picks)} articles verified")
    return found

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url"); ap.add_argument("--mark", action="append", required=True); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    try: print(make_card(a.url, a.mark, Path(a.out)))
    except ValueError as ex: sys.exit(f"[article] {ex}")

if __name__ == "__main__": main()
