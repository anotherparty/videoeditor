#!/usr/bin/env python3
"""
Reel Studio dashboard — local web UI over pipeline.py. No installs (Python stdlib only).

  python3 server.py [--port 8777]      ->  http://localhost:8777

Projects live in ~/Projects/Reels/<slug>/ (new ones are made there). Older project folders elsewhere
are listed in Reels/_index.json (a JSON list of absolute paths). Each project folder = project.json + source files,
work/, out/, out/phone/, status.json (see ../pipeline.py).
"""
import json, os, re, subprocess, sys, threading, time, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

HERE = Path(__file__).parent
SKILL = HERE.parent
ROOT = Path.home() / "Projects/Reels"
PIPE = SKILL / "pipeline.py"
PRESETS = SKILL / "presets"     # presets/<slug>.json = {"name", "look": {...}, "notes": [lessons]}
PRESET_KEYS = {"cta", "handle", "cap_style", "loudness"}   # per-video things (title card, date, tag) stay per project
RUNNING = {}            # project path -> Popen
ROOT.mkdir(parents=True, exist_ok=True)

def jsave(p, obj):
    """write JSON atomically (temp file + rename) so a reader never sees half a file"""
    p = Path(p); tmp = p.with_name(f".{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    with open(tmp, "w") as fh: json.dump(obj, fh, indent=1, ensure_ascii=False); fh.write("\n")
    os.replace(tmp, p)

def jload(p, d):
    try: return json.load(open(p))
    except Exception: return d

def projects():
    paths = [p for p in sorted(ROOT.iterdir()) if (p / "project.json").exists()]
    paths += [Path(x) for x in jload(ROOT / "_index.json", []) if (Path(x) / "project.json").exists()]
    return {re.sub(r"\W+", "-", p.name.lower()).strip("-"): p for p in paths}

def job_pid(p):
    """pid of this project's pipeline if it's alive — also after a dashboard restart (pid file + the process's command line)"""
    if p in RUNNING and RUNNING[p].poll() is None: return RUNNING[p].pid
    try: pid = int((p / "work" / "pipeline.pid").read_text())
    except Exception: return None
    cmd = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True).stdout
    return pid if "pipeline.py" in cmd and str(p) in cmd else None

def running(p): return job_pid(p) is not None

def spawn(p, *args):
    if running(p): return False
    log = open(p / "work" / "pipeline.log", "a") if (p / "work").exists() else subprocess.DEVNULL
    RUNNING[p] = subprocess.Popen(["python3", str(PIPE), str(p), *args], stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                                  start_new_session=True)     # keeps rendering if the dashboard restarts
    (p / "work").mkdir(exist_ok=True); (p / "work" / "pipeline.pid").write_text(str(RUNNING[p].pid))
    return True

def stale_out(p, n):
    """a video needs re-rendering: move it (and its phone copy) to out/_prev/ instead of deleting it"""
    for x in (p / "out" / f"{n}.mp4", p / "out" / "phone" / f"{n}.mp4"):
        if x.exists():
            prev = p / "out" / "_prev" / x.relative_to(p / "out"); prev.parent.mkdir(parents=True, exist_ok=True); os.replace(x, prev)

LIB = Path.home() / "Projects" / "Reels" / "_library"
VIDS, IMGS = {".mp4", ".mov", ".m4v"}, {".jpg", ".jpeg", ".png"}

CLAUDE = Path.home() / ".local" / "bin" / "claude"                       # Claude Code CLI (uses Adam's subscription)
CAPTION_PROMPT = Path.home() / ".config" / "another-party" / "caption_prompt.md"   # private: his voice + ig-caption rules
ACCOUNTS = SKILL / "registry" / "accounts.json"   # {"@anotherparty25": {"hashtags": "#a #b"}}
DEFAULT_ACCOUNTS = {"@anotherparty25": {"hashtags": "#formerlyincarcerated #reentry #prisonreform #massincarceration #secondchances"}}

def window_text(p, video):
    """what Adam says in this video (the reel's window, or everything for the full video)"""
    cfg = jload(p / "project.json", {}); w = next((r.get("window", "") for r in cfg.get("reels", []) if r["name"] == video), "")
    lo, hi = (map(float, w.split("-")) if w else (0, 1e9))
    return " ".join(r["text"] for r in lines(p) if r["end"] >= lo and r["start"] <= hi), lo, hi

CLAUDE_STATE = Path.home() / ".config" / "another-party" / "claude_state.json"   # last result of calling Claude

def ask_claude(prompt, timeout=180):
    """claude -p -> (stdout, error); remembers whether Claude was signed in for the health check"""
    if not CLAUDE.exists(): return "", "Claude Code isn't installed"
    r = subprocess.run([str(CLAUDE), "-p", prompt, "--output-format", "text"], capture_output=True, text=True, timeout=timeout,
                       stdin=subprocess.DEVNULL, cwd=str(Path.home()))
    out = r.stdout + r.stderr
    state = "needs_login" if "not logged in" in out.lower() or "/login" in out else ("ok" if r.returncode == 0 else "error")
    jsave(CLAUDE_STATE, {"state": state, "when": time.strftime("%Y-%m-%d %H:%M"), "detail": out.strip()[-200:]})
    if state == "needs_login": return "", "Claude needs you to sign in once: open Terminal, run ~/.local/bin/claude and type /login"
    return r.stdout, (None if r.returncode == 0 else out.strip()[-300:])

def write_caption(p, video):
    """Claude writes the caption from the transcript (claude -p, 3 min max) -> cfg["post"][video]"""
    text, _, _ = window_text(p, video)
    prompt = CAPTION_PROMPT.read_text() + "\n\n# Reel transcript\n" + text[:6000]
    stdout, err = ask_claude(prompt)
    if err: return {"error": err}
    m = re.search(r"\{.*\}", stdout, re.S)
    try: out = json.loads(m.group(0)) if m else None
    except Exception: out = None
    if not out: return {"error": "Claude didn't return a caption: " + stdout[-300:]}
    return out

INSP = ROOT / "_inspiration"      # your look board: files + items.json (local only, never in the public repo)
LIKES = ["Captions", "Colors", "Pacing / cuts", "B-roll", "Text cards", "Transitions", "Music / sound", "Framing", "The hook", "Other"]

def insp_items(): return jload(INSP / "items.json", [])

def insp_to_preset(it):
    """an inspiration's likes + note become a lesson in its project type's notes (I read those before every project)"""
    if not it.get("preset") or not (it.get("likes") or it.get("note")): return
    pp = PRESETS / f"{it['preset']}.json"; pre = jload(pp, None)
    if pre is None: return
    tag = f"[inspiration {it['id']}]"
    line = f"{time.strftime('%Y-%m-%d')}: {tag} Adam likes the {', '.join(it.get('likes') or ['look']).lower()} in {it.get('title') or it.get('url') or it.get('file')}" \
           + (f" — {it['note'].strip()}" if it.get("note", "").strip() else "")
    pre["notes"] = [n for n in pre.get("notes", []) if tag not in n] + [line]; jsave(pp, pre)

def du(p):
    try: return int(subprocess.run(["du", "-sk", str(p)], capture_output=True, text=True).stdout.split()[0]) * 1024
    except Exception: return 0

def health():
    """everything Reel Studio depends on, in one list: [{name, ok, detail, fix}]"""
    import shutil
    chk = []
    add = lambda name, ok, detail, fix="", test="": chk.append({"name": name, "ok": bool(ok), "detail": detail, "fix": fix, "test": test})
    cs = jload(CLAUDE_STATE, {})
    add("Claude (captions)", CLAUDE.exists() and cs.get("state") == "ok",
        "not installed" if not CLAUDE.exists() else {"ok": f"signed in, working (checked {cs.get('when')})",
        "needs_login": "installed, but not signed in", "error": f"last call failed: {cs.get('detail', '')[:80]}"}.get(cs.get("state"), "installed, not tested yet"),
        "" if cs.get("state") == "ok" else "In Terminal run ~/.local/bin/claude, type /login, then press Test", "claude")
    add("Caption style file", CAPTION_PROMPT.exists(), str(CAPTION_PROMPT).replace(str(Path.home()), "~"))
    pk = Path.home() / ".config/another-party/pixabay_key"
    add("Pixabay stock footage", pk.exists(), "key saved" if pk.exists() else "no key: stock B-roll is skipped")
    venv = Path.home() / "Projects/wispr-flow-clone/.venv/bin/python"
    add("Transcription", venv.exists(), "Whisper (small.en) via the Wispr Flow clone's Python" if venv.exists() else "missing Python env")
    free = shutil.disk_usage(str(ROOT)).free
    add("Disk space", free > 20e9, f"{free / 1e9:.0f} GB free", "" if free > 20e9 else "Clean up old versions below, or archive projects")
    bk = subprocess.run(["launchctl", "list"], capture_output=True, text=True).stdout
    add("Nightly backup to iCloud", "com.adamroberts.reels-backup" in bk, "runs every night" if "com.adamroberts.reels-backup" in bk else "not loaded")
    prev = sum(du(p / "out" / "_prev") for p in projects().values() if (p / "out" / "_prev").exists())
    return {"checks": chk, "reels_bytes": du(ROOT), "prev_bytes": prev, "projects": len(projects())}

def yt_id(url):
    m = re.search(r"(?:youtu\.be/|v=|shorts/|embed/)([\w-]{11})", url or ""); return m.group(1) if m else None

def lines(p):
    """the transcript as short lines [{start, end, text}] — a new line at a sentence/clause end (5+ words), 14 words, or a pause"""
    cfg = jload(p / "project.json", {})
    tj = p / "work" / (Path(cfg.get("video", "x")).stem + ".json")
    words = sorted((w for s in jload(tj, {}).get("segments", []) for w in s.get("words", [])), key=lambda w: w["start"])
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w); nxt = words[i + 1] if i + 1 < len(words) else None
        txt = w["word"].strip()
        if not nxt or len(cur) >= 14 or (len(cur) >= 5 and txt[-1:] in ".,?!;:") or nxt["start"] - w["end"] > 0.8:
            out.append({"start": round(cur[0]["start"], 2), "end": round(cur[-1]["end"], 2), "text": " ".join(x["word"].strip() for x in cur)}); cur = []
    return out

def detail(pid, p):
    cfg = jload(p / "project.json", {})
    st = jload(p / "status.json", {"state": "idle"})
    if st.get("state") == "running" and not running(p): st["state"] = "stopped"
    jobs = (["full"] if cfg.get("make_full", True) else []) + [r["name"] for r in cfg.get("reels", [])]
    outs = []
    for n in jobs:
        f, ph = p / "out" / f"{n}.mp4", p / "out" / "phone" / f"{n}.mp4"
        reel = next((r for r in cfg.get("reels", []) if r["name"] == n), None)
        outs.append({"name": n, "tag": cfg.get("full_tag", "Full video") if n == "full" else (reel or {}).get("tag", n),
                     "on": True if n == "full" else (reel or {}).get("on", True),
                     "window": (reel or {}).get("window", ""),
                     "url": f"/files/{pid}/out/{n}.mp4" if f.exists() else None,
                     "phone": f"/files/{pid}/out/phone/{n}.mp4" if ph.exists() else None,
                     "mb": round(f.stat().st_size / 1e6, 1) if f.exists() else 0,
                     "phone_mb": round(ph.stat().st_size / 1e6, 1) if ph.exists() else 0,
                     "mtime": f.stat().st_mtime if f.exists() else 0,
                     "plan": jload(p / "work" / f"{n}.plan.json", []),
                     "cuts": (p / "work" / f"{n}.cuts.txt").read_text().strip() if (p / "work" / f"{n}.cuts.txt").exists() else "",
                     "prev": f"/files/{pid}/out/_prev/{n}.mp4" if (p / "out" / "_prev" / f"{n}.mp4").exists() and not f.exists() else None,
                     "posting": cfg.get("posting", {}).get(n, {}), "post": cfg.get("post", {}).get(n, {}),
                     "cover": f"/files/{pid}/out/{n}.cover.jpg?v={int((p / 'out' / f'{n}.cover.jpg').stat().st_mtime)}" if (p / "out" / f"{n}.cover.jpg").exists() else None})
    log = ""
    lp = p / "work" / "pipeline.log"
    if lp.exists():
        lines = [l for l in lp.read_text(errors="ignore").splitlines() if l.startswith("[") or l.startswith("ERROR")]
        log = "\n".join(lines[-14:])
    look = p / "out" / "look.jpg"
    return {"id": pid, "path": str(p), "cfg": cfg,
            "look": f"/files/{pid}/out/look.jpg?v={int(look.stat().st_mtime)}" if look.exists() else None, "status": st, "running": running(p), "outputs": outs,
            "suggestions": jload(p / "work" / "suggestions.json", []), "log": log,
            "has_transcript": bool(cfg.get("video")) and (p / "work" / (Path(cfg["video"]).stem + ".json")).exists()}

LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]"}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def trusted(self, write):
        """only this Mac's own browser tab may use the dashboard: the Host must be local (blocks DNS rebinding), and
        anything that changes something must come from the dashboard page itself (blocks other sites posting here)"""
        if (self.headers.get("Host") or "").rsplit(":", 1)[0] not in LOCAL_HOSTS: return False
        if not write: return True
        src = self.headers.get("Origin") or self.headers.get("Referer") or ""
        return urllib.parse.urlparse(src).hostname in {"localhost", "127.0.0.1", "::1"}

    def send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(b)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def do_GET(self):
        if not self.trusted(False): return self.send(403, {"error": "local only"})
        u = urllib.parse.urlparse(self.path); parts = [urllib.parse.unquote(x) for x in u.path.strip("/").split("/")]
        if u.path in ("/", "/index.html"):
            return self.send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        if parts[:2] == ["api", "presets"]:    # project types for the "Add" picker
            return self.send(200, [{"id": f.stem, "name": jload(f, {}).get("name", f.stem), "blurb": jload(f, {}).get("blurb", "")}
                                   for f in sorted(PRESETS.glob("*.json"))])
        if parts[:2] == ["api", "projects"]:
            out = []
            for pid, p in projects().items():
                cfg = jload(p / "project.json", {}); st = jload(p / "status.json", {})
                out.append({"id": pid, "name": cfg.get("name", p.name), "state": "running" if running(p) else st.get("state", "idle"),
                            "videos": len(list((p / "out").glob("*.mp4"))) if (p / "out").exists() else 0,
                            "mtime": (p / "project.json").stat().st_mtime})
            return self.send(200, sorted(out, key=lambda x: -x["mtime"]))
        if parts[:2] == ["api", "accounts"]:
            return self.send(200, jload(ACCOUNTS, DEFAULT_ACCOUNTS))
        if parts[:2] == ["api", "inspiration"]:
            return self.send(200, {"items": insp_items(), "likes": LIKES})
        if parts[:2] == ["api", "health"]:
            return self.send(200, health())
        if parts[0] == "insp" and len(parts) == 2:
            f = (INSP / parts[1]).resolve()
            return self.file(f) if f.parent == INSP.resolve() and f.is_file() else self.send(404, {"error": "no file"})
        if parts[:2] == ["api", "library"]:    # your B-roll library, for the drag tray
            return self.send(200, [{"name": f.name, "path": str(f), "video": f.suffix.lower() in VIDS}
                                   for f in sorted(LIB.iterdir()) if f.suffix.lower() in VIDS | IMGS] if LIB.is_dir() else [])
        if parts[0] == "lib" and len(parts) == 2:
            f = (LIB / parts[1]).resolve()
            return self.file(f) if f.parent == LIB.resolve() and f.is_file() else self.send(404, {"error": "no file"})
        if parts[0] == "api" and len(parts) == 4 and parts[1] == "p" and parts[3] == "lines":
            p = projects().get(parts[2])
            return self.send(200, lines(p)) if p else self.send(404, {"error": "no project"})
        if parts[0] == "api" and len(parts) >= 3 and parts[1] == "p":
            p = projects().get(parts[2])
            return self.send(200, detail(parts[2], p)) if p else self.send(404, {"error": "no project"})
        if parts[0] == "files" and len(parts) >= 3:
            p = projects().get(parts[1])
            if not p: return self.send(404, {"error": "no project"})
            f = (p / "/".join(parts[2:])).resolve()
            if not str(f).startswith(str(p.resolve())) or not f.is_file(): return self.send(404, {"error": "no file"})
            return self.file(f)
        self.send(404, {"error": "not found"})

    def file(self, f: Path):
        size = f.stat().st_size
        ctype = {".mp4": "video/mp4", ".mov": "video/quicktime", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                 ".png": "image/png"}.get(f.suffix.lower(), "application/octet-stream")
        rng = self.headers.get("Range"); start, end = 0, size - 1
        if rng and (m := re.match(r"bytes=(\d*)-(\d*)", rng)):
            if m.group(1): start = int(m.group(1))
            if m.group(2): end = min(size - 1, int(m.group(2)))
            self.send_response(206); self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        dl = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("dl")
        if dl: self.send_header("Content-Disposition", f'attachment; filename="{f.name}"')
        self.send_header("Content-Type", ctype); self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1)); self.end_headers()
        with open(f, "rb") as fh:
            fh.seek(start); left = end - start + 1
            try:
                while left > 0:
                    chunk = fh.read(min(1 << 20, left))
                    if not chunk: break
                    self.wfile.write(chunk); left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError): pass

    def do_PUT(self):   # raw upload: /api/p/<id>/upload?name=..&kind=video|shot|broll
        if not self.trusted(True): return self.send(403, {"error": "only the dashboard page can do that"})
        u = urllib.parse.urlparse(self.path); parts = u.path.strip("/").split("/"); q = urllib.parse.parse_qs(u.query)
        if parts[:2] == ["api", "library"]:            # a photo / clip for your B-roll library
            LIB.mkdir(parents=True, exist_ok=True); name = re.sub(r"[^\w.\- ]", "_", Path(q.get("name", ["file"])[0]).name)
            n = int(self.headers.get("Content-Length") or 0)
            with open(LIB / name, "wb") as fh:
                while n > 0:
                    chunk = self.rfile.read(min(1 << 20, n))
                    if not chunk: break
                    fh.write(chunk); n -= len(chunk)
            return self.send(200, {"ok": True})
        if parts[:2] == ["api", "inspiration"]:        # a screenshot / clip for the look board
            INSP.mkdir(parents=True, exist_ok=True)
            name = time.strftime("%Y%m%d-%H%M%S-") + re.sub(r"[^\w.\- ]", "_", Path(q.get("name", ["file"])[0]).name)
            n = int(self.headers.get("Content-Length") or 0)
            with open(INSP / name, "wb") as fh:
                while n > 0:
                    chunk = self.rfile.read(min(1 << 20, n))
                    if not chunk: break
                    fh.write(chunk); n -= len(chunk)
            items = insp_items(); it = {"id": str(time.time_ns()), "file": name, "title": q.get("name", [""])[0],
                                        "video": Path(name).suffix.lower() in VIDS, "added": time.strftime("%Y-%m-%d"), "likes": [], "note": "", "preset": ""}
            items.insert(0, it); jsave(INSP / "items.json", items); return self.send(200, {"ok": True, "id": it["id"]})
        p = projects().get(parts[2]) if len(parts) > 3 else None
        if not p or parts[3] != "upload": return self.send(404, {"error": "bad upload"})
        name = re.sub(r"[^\w.\- ]", "_", Path(q.get("name", ["file"])[0]).name)
        src = p / "source"; src.mkdir(exist_ok=True)
        n = int(self.headers.get("Content-Length") or 0)
        with open(src / name, "wb") as fh:
            while n > 0:
                chunk = self.rfile.read(min(1 << 20, n))
                if not chunk: break
                fh.write(chunk); n -= len(chunk)
        cfg = jload(p / "project.json", {})
        if q.get("kind", ["shot"])[0] == "broll":          # hand-placed B-roll: just store it, the drop says where it goes
            return self.send(200, {"ok": True, "path": f"source/{name}"})
        if q.get("kind", ["shot"])[0] == "video":
            cfg["video"] = f"source/{name}"; cfg["reels"] = []
        else:
            cfg.setdefault("shots", []); cfg["shots"] = [s for s in cfg["shots"] if s != f"source/{name}"] + [f"source/{name}"]
        jsave(p / "project.json", cfg)
        if q.get("kind", ["shot"])[0] == "video": spawn(p, "--suggest")      # transcribe + title ideas right away
        self.send(200, {"ok": True})

    def do_POST(self):
        if not self.trusted(True): return self.send(403, {"error": "only the dashboard page can do that"})
        parts = self.path.strip("/").split("/")
        try: data = json.loads(self.body() or b"{}")
        except Exception: data = {}
        if parts[:2] == ["api", "projects"]:
            name = (data.get("name") or "New project").strip()
            slug = re.sub(r"\W+", "-", name.lower()).strip("-") or "project"
            p = ROOT / slug; i = 2
            while p.exists(): p = ROOT / f"{slug}-{i}"; i += 1
            (p / "source").mkdir(parents=True); (p / "work").mkdir(); (p / "out" / "phone").mkdir(parents=True)
            cfg = {"name": name, "video": "", "shots": [], "sticker": "", "date": time.strftime("%-m/%-d/%y"),
                   "cta": "Read the Substack", "handle": "adamrobertswrites.substack.com", "cap_style": "btb",
                   "make_full": True, "full_tag": "Full video", "reels": [], "posting": {}}
            preset = data.get("preset") or "another-party"          # a new project starts from its preset's look
            cfg.update(jload(PRESETS / f"{preset}.json", {}).get("look", {})); cfg["preset"] = preset
            jsave(p / "project.json", cfg)
            return self.send(200, {"id": re.sub(r"\W+", "-", p.name.lower()).strip("-")})
        if parts[:2] == ["api", "inspiration"]:   # {url} add a link | {id, likes?, note?, preset?} update | {id, delete}
            INSP.mkdir(parents=True, exist_ok=True); items = insp_items()
            if data.get("url"):
                it = {"id": str(time.time_ns()), "url": data["url"].strip(), "title": data.get("title", "") or data["url"].strip(),
                      "yt": yt_id(data["url"]), "added": time.strftime("%Y-%m-%d"), "likes": [], "note": "", "preset": ""}
                items.insert(0, it); jsave(INSP / "items.json", items); return self.send(200, {"ok": True, "id": it["id"]})
            it = next((x for x in items if x["id"] == data.get("id")), None)
            if not it: return self.send(404, {"error": "no item"})
            if data.get("delete"):
                items.remove(it)
                if it.get("file") and (INSP / it["file"]).exists(): os.replace(INSP / it["file"], INSP / f".deleted-{it['file']}")   # recoverable
                for pp in PRESETS.glob("*.json"):                       # take its lesson back out of the preset
                    pre = jload(pp, {}); keep = [n for n in pre.get("notes", []) if f"[inspiration {it['id']}]" not in n]
                    if keep != pre.get("notes", []): pre["notes"] = keep; jsave(pp, pre)
            else:
                it.update({k: data[k] for k in ("likes", "note", "preset", "title") if k in data}); insp_to_preset(it)
            jsave(INSP / "items.json", items); return self.send(200, {"ok": True})
        if parts[:2] == ["api", "library"]:     # {name, rename?} | {name, delete}: rename = new trigger words
            f = (LIB / data.get("name", "")).resolve()
            if f.parent != LIB.resolve() or not f.is_file(): return self.send(404, {"error": "no file"})
            if data.get("delete"): os.replace(f, LIB / f".deleted-{f.name}")
            elif data.get("rename"):
                new = re.sub(r"[^\w.\- ]", "_", data["rename"].strip()).replace(" ", "-") + f.suffix.lower()
                if (LIB / new).exists(): return self.send(200, {"error": "a file with that name exists"})
                os.replace(f, LIB / new)
            return self.send(200, {"ok": True})
        if parts[:2] == ["api", "claude_test"]:   # tiny call (a few tokens) to check Claude is signed in
            out, err = ask_claude("Reply with just: ok", timeout=60); return self.send(200, {"ok": not err, "error": err})
        if parts[:2] == ["api", "cleanup"]:     # delete the kept previous versions of re-rendered videos
            import shutil
            for p in projects().values():
                if (p / "out" / "_prev").exists(): shutil.rmtree(p / "out" / "_prev")
            return self.send(200, {"ok": True})
        if parts[:2] == ["api", "clip"]:        # {text} -> the Mac clipboard (browsers often block page clipboard writes)
            subprocess.run(["pbcopy"], input=data.get("text", ""), text=True); return self.send(200, {"ok": True})
        if parts[:2] == ["api", "accounts"]:    # {account, hashtags} -> saved hashtag set
            acc = jload(ACCOUNTS, DEFAULT_ACCOUNTS); acc.setdefault(data["account"], {})["hashtags"] = data.get("hashtags", "")
            jsave(ACCOUNTS, acc); return self.send(200, {"ok": True})
        if len(parts) < 4 or parts[:2] != ["api", "p"]: return self.send(404, {"error": "not found"})
        p = projects().get(parts[2]); act = parts[3]
        if not p: return self.send(404, {"error": "no project"})
        cfgp = p / "project.json"; cfg = jload(cfgp, {})
        save = lambda: jsave(cfgp, cfg)
        stale = lambda n: stale_out(p, n)
        if act == "settings":
            look = {"sticker", "date", "cta", "handle", "cap_style", "full_tag"}
            changed = {k for k in data if cfg.get(k) != data[k]}
            cfg.update({k: v for k, v in data.items() if k in look | {"name", "make_full"}}); save()
            if changed & look:            # the look changed: every video needs a fresh render, and a new look check
                for n in ["full"] + [r["name"] for r in cfg.get("reels", [])]: stale(n)
                cfg["look_ok"] = False; save()
            return self.send(200, {"ok": True})
        if act == "save_preset":          # {note?} -> this project's look (and a lesson) becomes the preset's
            pp = PRESETS / f"{cfg.get('preset') or 'another-party'}.json"; pre = jload(pp, {"name": pp.stem, "look": {}, "notes": []})
            pre.setdefault("look", {}).update({k: cfg[k] for k in PRESET_KEYS if k in cfg})
            if (data.get("note") or "").strip(): pre.setdefault("notes", []).append(time.strftime("%Y-%m-%d: ") + data["note"].strip())
            jsave(pp, pre)
            return self.send(200, {"ok": True, "preset": pp.stem})
        if act in ("broll_add", "broll_del"):   # {path, start, end} | {i}: B-roll dragged onto a transcript line
            mb = cfg.setdefault("manual_broll", [])
            if act == "broll_add": mb.append({"path": data["path"], "start": float(data["start"]), "end": float(data["end"])}); t0 = float(data["start"])
            else: t0 = mb.pop(int(data["i"]))["start"] if 0 <= int(data["i"]) < len(mb) else None
            save()
            if t0 is not None:            # re-render only the videos that cover that moment
                for n in ["full"] + [r["name"] for r in cfg.get("reels", [])]:
                    w = next((r.get("window", "") for r in cfg.get("reels", []) if r["name"] == n), "")
                    if not w or float(w.split("-")[0]) <= t0 <= float(w.split("-")[1]): stale(n)
            return self.send(200, {"ok": True})
        if act == "caption":              # {video} -> Claude writes caption + hashtags + alt text in Adam's voice
            out = write_caption(p, data["video"])
            if "error" in out: return self.send(200, out)
            cfg = jload(cfgp, {}); post = cfg.setdefault("post", {}).setdefault(data["video"], {})
            post.update(caption=out.get("caption", ""), alt_hook=out.get("alt_hook", ""), alt_text=out.get("alt_text", ""),
                        flags=out.get("flags", []), tags=" ".join(out.get("hashtags", [])))
            jsave(cfgp, cfg); return self.send(200, {"ok": True})
        if act == "post_save":            # {video, caption?, tags?, alt_text?} -> your edits
            post = cfg.setdefault("post", {}).setdefault(data["video"], {})
            post.update({k: data[k] for k in ("caption", "tags", "alt_text") if k in data}); save(); return self.send(200, {"ok": True})
        if act == "cover":                # {video, step?} -> cover.jpg from the source video, logo + title in the 3:4 safe area
            _, lo, hi = window_text(p, data["video"]); post = cfg.setdefault("post", {}).setdefault(data["video"], {})
            at = post.get("cover_at", lo + 3) + float(data.get("step", 0))
            vlen = max((r["end"] for r in lines(p)), default=lo + 10)
            if at > min(hi, vlen) - 1: at = lo + 1            # past the end: wrap around
            out = p / "out" / f"{data['video']}.cover.jpg"
            r = subprocess.run(["swift", str(SKILL / "cover.swift"), "--in", str(p / cfg["video"]), "--at", f"{at:.2f}",
                                "--title", cfg.get("sticker") or cfg.get("name", ""), "--date", cfg.get("date", ""), "--out", str(out)],
                               capture_output=True, text=True, timeout=120)
            if not out.exists(): return self.send(200, {"error": "cover failed: " + r.stderr[-300:]})
            post["cover_at"] = round(at, 2); save(); return self.send(200, {"ok": True})
        if act == "reel":                 # {name, on?, tag?}
            for r in cfg.get("reels", []):
                if r["name"] == data.get("name"):
                    if "tag" in data and data["tag"] != r.get("tag"): r["tag"] = data["tag"]; stale(r["name"])
                    if "on" in data: r["on"] = bool(data["on"])
            save(); return self.send(200, {"ok": True})
        if act in ("move", "move_reset"):  # {video, id, s, e} -> timeline drag: that graphic's new source-time span
            mp = p / "work" / f"{data['video']}.moves.json"; mv = jload(mp, {}) if act == "move" else {}
            if act == "move": mv[data["id"]] = [round(float(data["s"]), 2), round(float(data["e"]), 2)]
            jsave(mp, mv); stale(data["video"])
            planp = p / "work" / f"{data['video']}.plan.json"; plan = jload(planp, [])   # show it moved right away
            for it in plan:
                if it["id"] in mv: it["src"] = mv[it["id"]]; it["moved"] = True
            if plan: jsave(planp, plan)
            return self.send(200, {"ok": True})
        if act == "toggle":               # {video, id, on} -> off-list for that video, output marked stale
            offp = p / "work" / f"{data['video']}.off.json"; off = set(jload(offp, []))
            (off.discard if data.get("on") else off.add)(data["id"])
            jsave(offp, sorted(off)); stale(data["video"])
            return self.send(200, {"ok": True})
        if act == "posting":              # {video, platform, value}
            cfg.setdefault("posting", {}).setdefault(data["video"], {})[data["platform"]] = data.get("value", "")
            save(); return self.send(200, {"ok": True})
        if act == "render":
            args = (["--pick"] if data.get("pick") else []) + (["--only", data["only"]] if data.get("only") else [])
            if data.get("pick"):
                for r in cfg.get("reels", []): stale(r["name"])
            return self.send(200, {"started": spawn(p, *args)})
        if act == "approve":              # "Looks good, make the rest"
            cfg["look_ok"] = True; save()
            return self.send(200, {"started": spawn(p)})
        if act == "archive":              # out of the list, folder kept in Reels/_archive/
            if running(p): return self.send(200, {"error": "stop the render first"})
            (ROOT / "_archive").mkdir(exist_ok=True); dest = ROOT / "_archive" / p.name
            if dest.exists(): dest = ROOT / "_archive" / f"{p.name}-{int(time.time())}"
            os.replace(p, dest); return self.send(200, {"ok": True})
        if act == "suggest":
            return self.send(200, {"started": spawn(p, "--suggest")})
        if act == "stop":
            pid = job_pid(p)
            if pid: os.killpg(pid, 15)        # the whole job (swift renders included), it runs in its own session
            return self.send(200, {"ok": True})
        self.send(404, {"error": "unknown action"})

if __name__ == "__main__":
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8777
    print(f"Reel Studio on http://localhost:{port}  (projects: {ROOT})", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
