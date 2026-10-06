#!/usr/bin/env python3
"""
pipeline.py — one project folder in, finished full cut + reels out. The dashboard runs this; so can Claude.

  python3 pipeline.py PROJECT_DIR [--only NAME] [--force] [--pick]   # render (and auto-pick reels if none)
  python3 pipeline.py PROJECT_DIR --suggest                         # title-card suggestions -> stdout JSON

PROJECT_DIR/project.json (paths relative to PROJECT_DIR):
  {"name", "video", "shots": [...], "sticker", "date", "cta", "handle", "cap_style": "btb|box|mono",
   "make_full": true, "full_tag", "reels": [{"name","window","tag","on"}], "posting": {...}}
Writes work/ (transcript, plans, off-lists), out/NAME.mp4, out/phone/NAME.mp4, status.json, work/pipeline.log.
Steps per video: dead-air cut -> captions -> autoplan (labels, places, emoji, stock, screenshots) -> editplan
-> stagereel (face-clear captions, split/full B-roll) -> phone copy. Each output is skipped if it exists
unless --force or its plan/settings changed (the dashboard deletes the output when you toggle an item).
"""
import argparse, json, re, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).parent
VENV_PY = Path.home() / "Projects/wispr-flow-clone/.venv/bin/python"
COMPRESS = HERE / "compress.swift"

def jload(p, d):
    try: return json.load(open(p))
    except Exception: return d

class Run:
    def __init__(self, proj: Path):
        self.p = proj; self.work = proj / "work"; self.out = proj / "out"
        for d in (self.work, self.out, self.out / "phone"): d.mkdir(parents=True, exist_ok=True)
        self.cfg = jload(proj / "project.json", {})
        self.log = open(self.work / "pipeline.log", "a")
        self.status = {"state": "running", "step": "", "job": "", "done": [], "errors": [], "started": time.time()}

    def say(self, step, job=""):
        self.status.update(step=step, job=job, updated=time.time())
        json.dump(self.status, open(self.p / "status.json", "w"))
        self.log.write(f"[{time.strftime('%H:%M:%S')}] {job} {step}\n"); self.log.flush()

    def sh(self, cmd, **kw):
        self.log.write("$ " + " ".join(map(str, cmd)) + "\n"); self.log.flush()
        r = subprocess.run(list(map(str, cmd)), capture_output=True, text=True, stdin=subprocess.DEVNULL, **kw)
        self.log.write(r.stdout[-4000:] + "\n" + "\n".join(l for l in r.stderr.splitlines() if "warning" not in l.lower() and "|" not in l)[-3000:] + "\n")
        self.log.flush()
        if r.returncode != 0: raise RuntimeError(f"{Path(str(cmd[1])).name} failed (see work/pipeline.log)")
        return r.stdout

    def save_cfg(self): json.dump(self.cfg, open(self.p / "project.json", "w"), indent=1, ensure_ascii=False)

    def transcript(self):
        src = self.p / self.cfg["video"]; tj = self.work / (src.stem + ".json")
        if not tj.exists():
            self.say("transcribing (a minute or two)")
            self.sh([VENV_PY, HERE / "transcribe.py", src, "--model", "small.en", "--out-dir", self.work])
        return tj

    def shot_names(self):
        shots = [str(self.p / s) for s in self.cfg.get("shots", [])]
        if not shots: return []
        ocr = json.loads(self.sh(["swift", HERE / "ocr.swift", *shots]) or "{}")
        text = " " + " ".join(re.sub(r"[^a-z0-9' ]", "", l["text"].lower()) for v in ocr.values() for l in v.get("lines", [])) + " "
        people = jload(HERE / "registry/people.json", [])
        return [k for p in people for k in p["keys"] if f" {k} " in text] + ["substack", "published", "article"]

    def pick(self, tj):
        self.say("picking reels")
        reels = json.loads(self.sh(["python3", HERE / "reelpick.py", tj, "--n", "4", "--boost", *self.shot_names()]))
        self.cfg["reels"] = [dict(r, on=True) for r in reels]; self.save_cfg()

    def job(self, tj, name, window, tag, force):
        out = self.out / f"{name}.mp4"
        if out.exists() and not force: self.status["done"].append(name); return
        style = self.cfg.get("cap_style", "btb")
        mw, mc = (3, 16) if style == "btb" else (6, 30)
        self.say("cutting dead air", name)
        cuts = self.sh(["python3", HERE / "deadair.py", tj, "--gap", "0.7", "--pad", "0.15", *(["--within", window] if window else [])]).strip()
        self.sh(["python3", HERE / "makecaptions.py", tj, "--cuts", cuts, "--max-words", mw, "--max-chars", mc, "--out", self.work / f"{name}.cues.json"])
        self.say("planning graphics", name)
        shots = [str(self.p / s) for s in self.cfg.get("shots", [])]
        self.sh(["python3", HERE / "autoplan.py", tj, "--cuts", cuts, "--work", self.work / "auto", "--out", self.work / f"{name}.beats.json",
                 "--plan", self.work / f"{name}.plan.json", "--off", self.work / f"{name}.off.json", *(["--shots", *shots] if shots else [])])
        self.sh(["python3", HERE / "editplan.py", tj, "--cuts", cuts, self.work / f"{name}.beats.json", "--out", self.work / f"{name}.edit.json"])
        self.say("rendering", name)
        c = self.cfg
        self.sh(["swift", HERE / "stagereel.swift", "--in", self.p / c["video"], "--out", out, "--cuts", cuts,
                 "--cues", self.work / f"{name}.cues.json", "--edit", self.work / f"{name}.edit.json",
                 "--style", "btb", "--cap-style", style, "--date", c.get("date", ""), "--tag", tag or c.get("name", ""),
                 "--sticker", c.get("sticker", c.get("name", "")), "--cta", c.get("cta", "Read the Substack"),
                 "--handle", c.get("handle", "adamrobertswrites.substack.com")])
        self.say("making phone copy", name)
        self.sh(["swift", COMPRESS, out, self.out / "phone" / f"{name}.mp4", "1000000" if name == "full" else "1200000"])
        self.status["done"].append(name)

def suggest(tj):
    """3-5 short title-card options straight from the transcript (punchy fragments with strong words)."""
    words = [w for s in jload(tj, {"segments": []})["segments"] for w in s.get("words", [])]
    text = " ".join(w["word"].strip() for w in words)
    frags = [f.strip(" ,.") for f in re.split(r"[.,!?;]| and | but | so ", text) if 2 <= len(f.split()) <= 7]
    strong = {"sick", "dayquil", "parole", "puppy", "attica", "sun", "free", "life", "miracle", "prison", "love",
              "bullshit", "offended", "home", "first", "never", "years", "grateful"} | set(jload(HERE / "registry/emoji.json", {}))
    scored = sorted({f for f in frags}, key=lambda f: -sum(re.sub(r"\W", "", w.lower()) in strong for w in f.split()))
    return [f[0].upper() + f[1:] for f in scored[:5]]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project"); ap.add_argument("--only"); ap.add_argument("--force", action="store_true")
    ap.add_argument("--pick", action="store_true"); ap.add_argument("--suggest", action="store_true")
    a = ap.parse_args()
    r = Run(Path(a.project).expanduser())
    try:
        tj = r.transcript()
        if a.suggest:
            sug = suggest(tj); json.dump(sug, open(r.work / "suggestions.json", "w"), ensure_ascii=False)
            print(json.dumps(sug, ensure_ascii=False)); r.status["state"] = "idle"; r.say("ready"); return
        if a.pick or not r.cfg.get("reels"): r.pick(tj)
        jobs = ([("full", "", r.cfg.get("full_tag", "Full video"))] if r.cfg.get("make_full", True) else []) + \
               [(x["name"], x["window"], x.get("tag", "")) for x in r.cfg.get("reels", []) if x.get("on", True)]
        for name, win, tag in jobs:
            if a.only and name != a.only: continue
            try: r.job(tj, name, win, tag, a.force or bool(a.only))
            except Exception as ex: r.status["errors"].append(f"{name}: {ex}"); r.log.write(f"ERROR {name}: {ex}\n")
        r.status["state"] = "done" if not r.status["errors"] else "done with errors"; r.say("finished")
    except Exception as ex:
        r.status["state"] = "failed"; r.status["errors"].append(str(ex)); r.say("failed")
        sys.exit(1)

if __name__ == "__main__": main()
