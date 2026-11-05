#!/usr/bin/env python3
"""Mechanical steps of the GTA6Short pipeline, so a batch of shorts runs the same way every time.

Usage (from the repo root):
  python3 -I scripts/pipeline.py status                 # news queue: id, status, title
  python3 -I scripts/pipeline.py new <slug> [news_id]   # shorts/<slug> from _template (+ link to news/<news_id>.json)
  python3 -I scripts/pipeline.py tts <slug>             # assets/audio/script.txt -> el/voice.mp3 + words.json (ElevenLabs, .env defaults)
  python3 -I scripts/pipeline.py build <slug>           # build_short + safe-zone check + one snapshot per beat
  python3 -I scripts/pipeline.py render <slug>          # delivery MP4 + loudness; news status -> review
  python3 -I scripts/pipeline.py set <news_id> <status> # todo | script | review | published | skip

The creative steps (script, shot choice, short.json) stay with Claude: see .claude/skills/gta6-short/SKILL.md.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NEWS = ROOT / "news"
SHORTS = ROOT / "shorts"
STATUSES = ("todo", "script", "review", "published", "skip")
# check findings that are known false positives with this template (see SKILL.md)
IGNORED = {"line_unread", "composition_file_too_large", "duplicate_audio_track", "contrast_aa_failure",
           "container_overflow", "canvas_overflow", "panel_out_of_canvas"}


def run(cmd, cwd=ROOT, capture=False):
    print("$", " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, cwd=cwd, check=True, text=True, capture_output=capture)


def json_tail(text):
    return json.loads(text[text.find("{"):])


def news_items():
    for f in sorted(NEWS.glob("*.json")):
        if not f.name.startswith("_"):
            yield f, json.loads(f.read_text())


def set_status(news_id, status, **extra):
    f = NEWS / f"{news_id}.json"
    d = json.loads(f.read_text())
    d["status"] = status
    d.update(extra)
    f.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n")
    print(f"news/{news_id}.json -> {status}")


def cmd_status():
    rows = list(news_items())
    if not rows:
        print("file vide : ajouter des sujets dans news/ (copier news/_TEMPLATE.json)")
    for f, d in rows:
        print(f"{d.get('status', 'todo'):<10} {f.stem:<28} {d.get('short', '-'):<24} {d.get('title', '')}")


def cmd_new(slug, news_id=None):
    sd = SHORTS / slug
    if sd.exists():
        sys.exit(f"{sd} existe déjà")
    shutil.copytree(SHORTS / "_template", sd)
    (sd / "assets/audio").mkdir(parents=True, exist_ok=True)
    if news_id:
        set_status(news_id, "script", short=slug)
    print(f"créé {sd.relative_to(ROOT)} — écrire assets/audio/script.txt puis short.json")


def cmd_tts(slug):
    a = SHORTS / slug / "assets/audio"
    run([sys.executable, "-I", "scripts/tts_elevenlabs.py", a / "script.txt", a / "el", "--speed", "1.1", "--stability", "0.5", "--style", "0"])
    words = json.loads((a / "el/words.json").read_text())
    print("mots:", " ".join(f"{w['text']}@{w['start']:.1f}" for w in words))


def cmd_build(slug):
    sd = SHORTS / slug
    out = run([sys.executable, "-I", "scripts/build_short.py", sd], capture=True).stdout
    print(out.strip())
    at = re.search(r"--at ([\d.,]+)", out).group(1)
    spec = json.loads((sd / "short.json").read_text())
    words = json.loads((sd / spec["words"]).read_text())
    total = words[-1]["end"] + spec.get("tail", 1.0)
    caps = ",".join(f"{t:.2f}" for t in [x * 1.7 + 0.9 for x in range(int(total / 1.7))])  # caption samples
    chk = json_tail(subprocess.run(["npx", "hyperframes", "check", "--json", "--at", f"{at},{caps}"], cwd=sd,
                                   text=True, capture_output=True).stdout)
    bad = []
    for k, v in chk.items():
        if isinstance(v, dict):
            for f in v.get("findings", []):
                if f["code"] in IGNORED or (f["code"] == "text_occluded" and re.search(r"-d\d", f.get("selector") or "")):
                    continue
                bad.append(f"{f['severity']:<7} {f['code']:<22} {f.get('selector')} @{f.get('time')}  {f['message'][:90]}")
    print("\n".join(bad) if bad else "check: aucune anomalie hors faux positifs connus")
    snap = json_tail(subprocess.run(["npx", "hyperframes", "snapshot", "--at", f"0,{at}", "--json"], cwd=sd,
                                    text=True, capture_output=True).stdout)
    print("captures à regarder :")
    print("\n".join(snap.get("contactSheets", [])))
    if any(x.startswith("error") for x in bad):
        sys.exit(1)


def cmd_render(slug):
    sd = SHORTS / slug
    mp4 = f"render/{slug}.mp4"
    run(["npx", "hyperframes", "render", "-q", "delivery", "-o", mp4, "--skill", "hyperframes"], cwd=sd)
    loud = subprocess.run(["ffmpeg", "-i", mp4, "-af", "ebur128=peak=true", "-f", "null", "-"], cwd=sd,
                          text=True, capture_output=True).stderr
    lufs = re.findall(r"I:\s+(-?[\d.]+) LUFS", loud)[-1]
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", mp4],
                         cwd=sd, text=True, capture_output=True).stdout.strip()
    print(f"{sd.relative_to(ROOT)}/{mp4}: {float(dur):.1f} s, {lufs} LUFS (cible -16..-14)")
    for f, d in news_items():
        if d.get("short") == slug:
            set_status(f.stem, "review", render=f"shorts/{slug}/{mp4}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    c, args = sys.argv[1], sys.argv[2:]
    {"status": cmd_status, "new": cmd_new, "tts": cmd_tts, "build": cmd_build, "render": cmd_render,
     "set": lambda i, s: set_status(i, s) if s in STATUSES else sys.exit(f"statut: {STATUSES}")}[c](*args)
