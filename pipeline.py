#!/usr/bin/env python3
"""
pipeline.py — one project folder in, finished full cut + reels out. The dashboard runs this; so can Claude.

  python3 pipeline.py PROJECT_DIR [--only NAME] [--force] [--pick]   # render (and auto-pick reels if none)
  python3 pipeline.py PROJECT_DIR --suggest                         # title-card suggestions -> stdout JSON
  python3 pipeline.py PROJECT_DIR --preview                         # look check: shortest video + out/look.jpg

Look gate (Adam, Oct 6 2026: "I want to see the look before you generate all the things"): until project.json
has "look_ok": true, a render only makes the preview (the shortest video plus a contact sheet of stills at its
graphics). The dashboard's "Looks good, make the rest" sets look_ok; changing the look resets it.

PROJECT_DIR/project.json (paths relative to PROJECT_DIR):
  {"name", "video", "shots": [...], "sticker", "date", "cta", "handle", "cap_style": "btb|box|mono",
   "make_full": true, "full_tag", "reels": [{"name","window","tag","on"}], "posting": {...}}
Writes work/ (transcript, plans, off-lists), out/NAME.mp4, out/phone/NAME.mp4, status.json, work/pipeline.log.
Steps per video: dead-air cut -> captions -> autoplan (labels, places, emoji, stock, screenshots) -> editplan
-> stagereel (face-clear captions, split/full B-roll) -> normalize (speech to reel loudness, limiter) -> phone copy. Each output is skipped if it exists
unless --force or its plan/settings changed (the dashboard deletes the output when you toggle an item).
"""
import argparse, json, os, re, subprocess, sys, threading, time
from pathlib import Path

HERE = Path(__file__).parent
VENV_PY = Path.home() / "Projects/wispr-flow-clone/.venv/bin/python"
COMPRESS = HERE / "compress.swift"

def jsave(p, obj):
    """write JSON atomically (temp file + rename) so a reader never sees half a file"""
    p = Path(p); tmp = p.with_name(f".{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    with open(tmp, "w") as fh: json.dump(obj, fh, indent=1, ensure_ascii=False); fh.write("\n")
    os.replace(tmp, p)

def jload(p, d):
    try: return json.load(open(p))
    except Exception: return d

# how tight the edit is (project setting "edit"): gap between words that counts as dead air, cut ums, cut stutters/repeats
EDITS = {"light": (0.7, False, False), "clean": (0.7, True, False), "ruthless": (0.35, True, True)}
def edit_args(name):
    gap, fill, rep = EDITS[name]
    return ["--gap", str(gap)] + (["--drop-fillers"] if fill else []) + (["--drop-repeats"] if rep else [])

class Run:
    def __init__(self, proj: Path):
        self.p = proj; self.work = proj / "work"; self.out = proj / "out"
        for d in (self.work, self.out, self.out / "phone"): d.mkdir(parents=True, exist_ok=True)
        self.cfg = jload(proj / "project.json", {})
        self.log = open(self.work / "pipeline.log", "a")
        self.status = {"state": "running", "step": "", "job": "", "done": [], "errors": [], "started": time.time()}

    def say(self, step, job=""):
        self.status.update(step=step, job=job, updated=time.time())
        jsave(self.p / "status.json", self.status)
        self.log.write(f"[{time.strftime('%H:%M:%S')}] {job} {step}\n"); self.log.flush()

    def sh(self, cmd, **kw):
        self.log.write("$ " + " ".join(map(str, cmd)) + "\n"); self.log.flush()
        r = subprocess.run(list(map(str, cmd)), capture_output=True, text=True, stdin=subprocess.DEVNULL, **kw)
        self.log.write(r.stdout[-4000:] + "\n" + "\n".join(l for l in r.stderr.splitlines() if "warning" not in l.lower() and "|" not in l)[-3000:] + "\n")
        self.log.flush()
        if r.returncode != 0: raise RuntimeError(f"{Path(str(cmd[1])).name} failed (see work/pipeline.log)")
        return r.stdout

    def save_cfg(self, *keys):
        """write back only the keys this run changed, on top of the file as it is NOW (the dashboard may have edited it)"""
        cur = jload(self.p / "project.json", None)
        if cur is None: return                      # unreadable right now: never overwrite with a partial copy
        cur.update({k: self.cfg[k] for k in keys}); jsave(self.p / "project.json", cur)

    def transcript(self):
        src = self.p / self.cfg["video"]; tj = self.work / (src.stem + ".json")
        if tj.exists() and EDITS[self.edit()][1] and not jload(tj, {}).get("fillers"):    # cutting ums needs them written down
            os.replace(tj, tj.with_suffix(".nofill.json"))                                # the old listen is kept
        if not tj.exists():
            self.say("transcribing (a minute or two)")
            self.sh([VENV_PY, HERE / "transcribe.py", src, "--model", "small.en", "--out-dir", self.work, "--fillers"])
        if not tj.with_suffix(".env.json").exists():                                      # loudness map: um cuts land in silence
            self.sh([VENV_PY, HERE / "transcribe.py", src, "--out-dir", self.work, "--env-only"])
        return tj

    def edit(self): return self.cfg.get("edit") if self.cfg.get("edit") in EDITS else "clean"

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
        self.cfg["reels"] = [dict(r, on=True) for r in reels]; self.save_cfg("reels")

    def look_sheet(self, name):
        """contact sheet of the rendered preview: opening frame + the middle of each kind of graphic"""
        plan = jload(self.work / f"{name}.plan.json", []); edit = jload(self.work / f"{name}.edit.json", {})
        ts, seen = [1.0], set()
        for g in edit.get("broll", []) + edit.get("graphics", []):
            k = g.get("type", "broll") + ("v" if g.get("video") else "") + g.get("layout", "") + ("m" if g.get("marks") else "")
            if k not in seen: seen.add(k); ts.append(round((g["start"] + g["end"]) / 2, 1))
        frames = self.work / "look"; frames.mkdir(exist_ok=True)
        for f in frames.glob("*.jpg"): f.unlink()
        self.sh(["swift", HERE / "grabframes.swift", self.out / f"{name}.mp4", frames, *[str(t) for t in sorted(ts)[:8]]])
        self.sh(["swift", HERE / "sheet.swift", self.out / "look.jpg", *sorted(map(str, frames.glob("frame_*.jpg")))])

    def kinds(self, name):
        """how many different kinds of graphics a video's plan shows (screenshot, stock, label, place, emoji)"""
        k = set()
        for x in jload(self.work / f"{name}.plan.json", []):
            if x.get("on"): k.add("stock" if str(x.get("id", "")).startswith("stock") else x.get("type"))
        return len(k)

    def job(self, tj, name, window, tag, force, plan_only=False):
        out = self.out / f"{name}.mp4"
        if out.exists() and not force and not plan_only: self.status["done"].append(name); return
        style = self.cfg.get("cap_style", "btb")
        mw, mc = (3, 16) if style == "btb" else (6, 30)
        self.say("cutting dead air", name)
        cuts = self.sh(["python3", HERE / "deadair.py", tj, *edit_args(self.edit()), "--pad", "0.15", *(["--within", window] if window else [])]).strip()
        (self.work / f"{name}.cuts.txt").write_text(cuts)      # the dashboard maps video time <-> transcript time with this
        self.sh(["python3", HERE / "makecaptions.py", tj, "--cuts", cuts, "--max-words", mw, "--max-chars", mc, "--out", self.work / f"{name}.cues.json"])
        self.say("planning graphics", name)
        shots = [str(self.p / s) for s in self.cfg.get("shots", [])]
        manual = self.work / "manual_broll.json"      # B-roll dragged onto transcript lines in the dashboard
        jsave(manual, [{**m, "path": str(self.p / m["path"])} for m in self.cfg.get("manual_broll", [])])
        self.sh(["python3", HERE / "autoplan.py", tj, "--cuts", cuts, "--work", self.work / "auto", "--out", self.work / f"{name}.beats.json",
                 "--plan", self.work / f"{name}.plan.json", "--off", self.work / f"{name}.off.json", "--manual", manual, "--moves", self.work / f"{name}.moves.json", "--pool", self.p / "source" / "broll", *(["--shots", *shots] if shots else []),
                 *(["--avoid", *self.cfg["shot_avoid"]] if self.cfg.get("shot_avoid") else []),
                 *(["--year", str(2000 + int(m[1]) % 100 if len(m[1]) == 2 else int(m[1]))] if (m := re.search(r"(\d{2}|\d{4})\s*$", self.cfg.get("date", ""))) else [])])   # "now" on the year strip = the project's date
        self.sh(["python3", HERE / "editplan.py", tj, "--cuts", cuts, self.work / f"{name}.beats.json", "--out", self.work / f"{name}.edit.json"])
        if plan_only: return
        self.say("rendering", name)
        c = self.cfg
        raw = self.work / f"{name}.raw.mp4"
        self.sh(["swift", HERE / "stagereel.swift", "--in", self.p / c["video"], "--out", raw, "--cuts", cuts,
                 "--cues", self.work / f"{name}.cues.json", "--edit", self.work / f"{name}.edit.json",
                 "--style", "btb", "--cap-style", style, "--date", c.get("date", ""), "--tag", tag or c.get("name", ""),
                 "--sticker", c.get("sticker", c.get("name", "")), "--cta", c.get("cta", "Read the Substack"),
                 "--handle", c.get("handle", "adamrobertswrites.substack.com")])
        # phone recordings are far too quiet for Instagram: bring speech up to reel level with a peak limiter
        self.say("fixing the sound level", name)
        self.sh(["swift", HERE / "normalize.swift", raw, out, "--target", str(c.get("loudness", -15))])
        raw.unlink()
        self.say("making phone copy", name)
        self.sh(["swift", COMPRESS, out, self.out / "phone" / f"{name}.mp4", "1000000" if name == "full" else "1200000"])
        self.status["done"].append(name)

def notify(title, msg):
    """Mac notification (renders take minutes; Adam shouldn't have to watch the page)"""
    q = lambda s: '"' + str(s).replace("\\", "").replace('"', "'") + '"'
    subprocess.run(["osascript", "-e", f"display notification {q(msg)} with title {q('Reel Studio')} subtitle {q(title)} sound name {q('Glass')}"],
                   capture_output=True)

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
    ap.add_argument("--preview", action="store_true")
    a = ap.parse_args()
    r = Run(Path(a.project).expanduser())
    try:
        tj = r.transcript()
        if a.suggest:
            sug = suggest(tj); jsave(r.work / "suggestions.json", sug)
            print(json.dumps(sug, ensure_ascii=False)); r.status["state"] = "idle"; r.say("ready"); return
        if a.pick or not r.cfg.get("reels"): r.pick(tj)
        jobs = ([("full", "", r.cfg.get("full_tag", "Full video"))] if r.cfg.get("make_full", True) else []) + \
               [(x["name"], x["window"], x.get("tag", "")) for x in r.cfg.get("reels", []) if x.get("on", True)]
        if a.preview or not r.cfg.get("look_ok"):
            # look gate: plan every video (fast), then render only the one that shows the most kinds of
            # graphics (shortest wins a tie) plus a sheet of stills, and stop for Adam's OK
            span = lambda j: (lambda w: float(w[1]) - float(w[0]))(j[1].split("-")) if j[1] else 1e9
            for n_, w_, t_ in jobs:
                r.say("planning graphics", n_); r.job(tj, n_, w_, t_, True, plan_only=True)
            name, win, tag = max(jobs, key=lambda j: (r.kinds(j[0]), -span(j)))
            r.say("rendering the look preview", name)
            r.job(tj, name, win, tag, True); r.look_sheet(name)
            r.cfg["look_preview"] = name; r.save_cfg("look_preview")
            r.status["state"] = "preview ready"; r.say("waiting for your OK on the look")
            notify(r.cfg.get("name", r.p.name), "Look preview ready, check it in Reel Studio"); return
        for name, win, tag in jobs:
            if a.only and name != a.only: continue
            try: r.job(tj, name, win, tag, a.force or bool(a.only))
            except Exception as ex: r.status["errors"].append(f"{name}: {ex}"); r.log.write(f"ERROR {name}: {ex}\n")
        r.status["state"] = "done" if not r.status["errors"] else "done with errors"; r.say("finished")
        notify(r.cfg.get("name", r.p.name), "All videos ready" if not r.status["errors"] else "Finished with errors, see the dashboard")
    except Exception as ex:
        r.status["state"] = "failed"; r.status["errors"].append(str(ex)); r.say("failed")
        notify(r.cfg.get("name", r.p.name), "Render failed: " + str(ex)[:80])
        sys.exit(1)

if __name__ == "__main__": main()
