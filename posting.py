#!/usr/bin/env python3
"""
posting.py — publish one finished video the way Adam's reels have always gone out: Claude drives his signed-in
Chrome (YouTube Studio, then Meta Business Suite for Instagram). Only ever started by Adam pressing Post.

  python3 posting.py PROJECT_DIR VIDEO_NAME --platforms youtube instagram [--dry-run]

Steps: under-10MB upload copy (out/upload/<video>_post.mp4, the Chrome upload tool's cap) -> post_prompt.md filled
with file, cover, title, caption + hashtags -> claude -p --chrome -> one JSON line back -> project.json
posting[<video>][platform] = "Oct 13 · <link>" and post_jobs[<video>] = {state, detail, when}.
--dry-run makes the copy and prints the filled prompt, posts nothing.
"""
import argparse, json, os, re, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).parent
CLAUDE = Path.home() / ".local/bin/claude"
CAP = 9_500_000                                   # bytes; Claude in Chrome's file upload stops at 10MB

def jload(p, d):
    try: return json.load(open(p))
    except Exception: return d

def update_cfg(p: Path, fn):
    """read-modify-write project.json atomically (the dashboard and pipeline write it too)"""
    cfgp = p / "project.json"; cfg = jload(cfgp, None)
    if cfg is None: return
    fn(cfg); tmp = cfgp.with_suffix(".tmp"); tmp.write_text(json.dumps(cfg, indent=1, ensure_ascii=False)); os.replace(tmp, cfgp)

def upload_copy(p: Path, n: str) -> Path:
    src = p / "out" / f"{n}.mp4"; dst = p / "out" / "upload" / f"{n}_post.mp4"
    if not src.exists(): raise ValueError(f"{n} isn't rendered yet")
    if src.stat().st_size <= CAP: return src
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime and dst.stat().st_size <= CAP: return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    br = int(src.stat().st_size * 8 / max(1.0, duration(src)) * CAP / src.stat().st_size * 0.92)
    for _ in range(3):                             # shrink the bitrate until it fits
        subprocess.run(["swift", str(HERE / "compress.swift"), str(src), str(dst), str(br)], capture_output=True, text=True)
        if dst.exists() and dst.stat().st_size <= CAP: return dst
        br = int(br * 0.8)
    raise ValueError("couldn't make an upload copy under 10MB")

def duration(f: Path) -> float:
    r = subprocess.run(["mdls", "-raw", "-name", "kMDItemDurationSeconds", str(f)], capture_output=True, text=True)
    try: return float(r.stdout)
    except ValueError: return 60.0

def build_prompt(p: Path, n: str, platforms) -> str:
    cfg = jload(p / "project.json", {}); post = cfg.get("post", {}).get(n, {})
    caption = (post.get("caption", "").strip() + "\n\n" + post.get("tags", "").strip()).strip()
    if not post.get("caption"): raise ValueError("write the caption first")
    if "—" in caption: raise ValueError("the caption has an em dash; fix it first")
    reel = next((r for r in cfg.get("reels", []) if r["name"] == n), {})
    title = post.get("title") or reel.get("tag") or cfg.get("full_tag") or cfg.get("name", n)
    cover = next((c for c in (p / "out" / f"{n}.cover.jpg", p / "out" / f"{n}-cover.jpg") if c.exists()), p / "out" / f"{n}.cover.jpg")
    fill = {"FILE": str(upload_copy(p, n)), "COVER": str(cover) if cover.exists() else "(none, skip the thumbnail)",
            "TITLE": title[:100], "CAPTION": caption, "PLATFORMS": ", ".join(platforms)}
    t = (HERE / "post_prompt.md").read_text()
    for k, v in fill.items(): t = t.replace("{{" + k + "}}", v)
    return t

def publish(p: Path, n: str, platforms, dry=False):
    stamp = lambda state, detail="": update_cfg(p, lambda c: c.setdefault("post_jobs", {}).__setitem__(
        n, {"state": state, "detail": detail, "when": time.strftime("%Y-%m-%d %H:%M"), "platforms": platforms}))
    try: prompt = build_prompt(p, n, platforms)
    except ValueError as ex: stamp("error", str(ex)); return {"error": str(ex)}
    if dry: print(prompt); return {"dry_run": True}
    stamp("posting", "Claude is posting in your Chrome (a few minutes)")
    try:
        r = subprocess.run([str(CLAUDE), "-p", prompt, "--chrome", "--allowedTools", "mcp__claude-in-chrome__*",
                            "--output-format", "text"], capture_output=True, text=True, timeout=1800,
                           stdin=subprocess.DEVNULL, cwd=str(Path.home()))
        m = re.findall(r"\{.*\}", r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "")
        res = json.loads(m[-1]) if m else None
    except Exception as ex: res = None; r = None; err = f"{type(ex).__name__}"
    if not res:
        detail = (r.stdout[-300:] if r else err) or "no answer from Claude"
        stamp("error", "Posting didn't finish. Check YouTube Studio and Business Suite before trying again. " + detail)
        return {"error": detail}
    day = time.strftime("%b %-d")
    def save(c):
        posting = c.setdefault("posting", {}).setdefault(n, {})
        for k, v in res.items():
            if isinstance(v, dict) and v.get("ok"): posting[k] = f"{day} · {v['url']}" if v.get("url") else day
    update_cfg(p, save)
    bad = {k: v.get("error", "") for k, v in res.items() if isinstance(v, dict) and not v.get("ok")}
    stamp("error" if bad else "done", "; ".join(f"{k}: {e}" for k, e in bad.items()) or "Posted")
    return res

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("project"); ap.add_argument("video")
    ap.add_argument("--platforms", nargs="+", default=["youtube", "instagram"], choices=["youtube", "instagram"])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    print(json.dumps(publish(Path(a.project).expanduser(), a.video, a.platforms, a.dry_run)))
