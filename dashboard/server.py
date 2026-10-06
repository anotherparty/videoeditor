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
RUNNING = {}            # project path -> Popen
ROOT.mkdir(parents=True, exist_ok=True)

def jload(p, d):
    try: return json.load(open(p))
    except Exception: return d

def projects():
    paths = [p for p in sorted(ROOT.iterdir()) if (p / "project.json").exists()]
    paths += [Path(x) for x in jload(ROOT / "_index.json", []) if (Path(x) / "project.json").exists()]
    return {re.sub(r"\W+", "-", p.name.lower()).strip("-"): p for p in paths}

def running(p): return p in RUNNING and RUNNING[p].poll() is None

def spawn(p, *args):
    if running(p): return False
    log = open(p / "work" / "pipeline.log", "a") if (p / "work").exists() else subprocess.DEVNULL
    RUNNING[p] = subprocess.Popen(["python3", str(PIPE), str(p), *args], stdout=log, stderr=log, stdin=subprocess.DEVNULL)
    return True

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
                     "posting": cfg.get("posting", {}).get(n, {})})
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

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(b)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def do_GET(self):
        u = urllib.parse.urlparse(self.path); parts = [urllib.parse.unquote(x) for x in u.path.strip("/").split("/")]
        if u.path in ("/", "/index.html"):
            return self.send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        if parts[:2] == ["api", "projects"]:
            out = []
            for pid, p in projects().items():
                cfg = jload(p / "project.json", {}); st = jload(p / "status.json", {})
                out.append({"id": pid, "name": cfg.get("name", p.name), "state": "running" if running(p) else st.get("state", "idle"),
                            "videos": len(list((p / "out").glob("*.mp4"))) if (p / "out").exists() else 0,
                            "mtime": (p / "project.json").stat().st_mtime})
            return self.send(200, sorted(out, key=lambda x: -x["mtime"]))
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

    def do_PUT(self):   # raw upload: /api/p/<id>/upload?name=..&kind=video|shot
        u = urllib.parse.urlparse(self.path); parts = u.path.strip("/").split("/"); q = urllib.parse.parse_qs(u.query)
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
        if q.get("kind", ["shot"])[0] == "video":
            cfg["video"] = f"source/{name}"; cfg["reels"] = []
        else:
            cfg.setdefault("shots", []); cfg["shots"] = [s for s in cfg["shots"] if s != f"source/{name}"] + [f"source/{name}"]
        json.dump(cfg, open(p / "project.json", "w"), indent=1, ensure_ascii=False)
        if q.get("kind", ["shot"])[0] == "video": spawn(p, "--suggest")      # transcribe + title ideas right away
        self.send(200, {"ok": True})

    def do_POST(self):
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
            json.dump(cfg, open(p / "project.json", "w"), indent=1)
            return self.send(200, {"id": re.sub(r"\W+", "-", p.name.lower()).strip("-")})
        if len(parts) < 4 or parts[:2] != ["api", "p"]: return self.send(404, {"error": "not found"})
        p = projects().get(parts[2]); act = parts[3]
        if not p: return self.send(404, {"error": "no project"})
        cfgp = p / "project.json"; cfg = jload(cfgp, {})
        save = lambda: json.dump(cfg, open(cfgp, "w"), indent=1, ensure_ascii=False)
        stale = lambda n: [x.unlink() for x in (p / "out" / f"{n}.mp4", p / "out" / "phone" / f"{n}.mp4") if x.exists()]
        if act == "settings":
            look = {"sticker", "date", "cta", "handle", "cap_style", "full_tag"}
            changed = {k for k in data if cfg.get(k) != data[k]}
            cfg.update({k: v for k, v in data.items() if k in look | {"name", "make_full"}}); save()
            if changed & look:            # the look changed: every video needs a fresh render, and a new look check
                for n in ["full"] + [r["name"] for r in cfg.get("reels", [])]: stale(n)
                cfg["look_ok"] = False; save()
            return self.send(200, {"ok": True})
        if act == "reel":                 # {name, on?, tag?}
            for r in cfg.get("reels", []):
                if r["name"] == data.get("name"):
                    if "tag" in data and data["tag"] != r.get("tag"): r["tag"] = data["tag"]; stale(r["name"])
                    if "on" in data: r["on"] = bool(data["on"])
            save(); return self.send(200, {"ok": True})
        if act == "toggle":               # {video, id, on} -> off-list for that video, output marked stale
            offp = p / "work" / f"{data['video']}.off.json"; off = set(jload(offp, []))
            (off.discard if data.get("on") else off.add)(data["id"])
            json.dump(sorted(off), open(offp, "w")); stale(data["video"])
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
        if act == "suggest":
            return self.send(200, {"started": spawn(p, "--suggest")})
        if act == "stop":
            if running(p): RUNNING[p].terminate()
            return self.send(200, {"ok": True})
        self.send(404, {"error": "unknown action"})

if __name__ == "__main__":
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8777
    print(f"Reel Studio on http://localhost:{port}  (projects: {ROOT})", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
