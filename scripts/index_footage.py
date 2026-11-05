#!/usr/bin/env python3
"""Index GTA6 footage: proxy transcode + scene detection + thumbnails + contact sheets.

Usage: .venv/bin/python -I scripts/index_footage.py [footage_dir ...]
Default dirs: footage/official footage/gameplay

Outputs:
  footage/proxy/<id>.mp4        H.264 1080p30, short GOP (fast frame-accurate seeking)
  catalog/thumbs/<id>/<n>.jpg   one mid-frame per shot
  catalog/sheets/<id>_<k>.jpg   contact sheets (for visual tagging by the agent)
  catalog/shots.json            shot list; existing tags are preserved on re-run
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROXY = ROOT / "footage" / "proxy"
CAT = ROOT / "catalog"
SCENE_THRESHOLD = 0.30
MIN_SHOT = 0.6  # seconds; shorter shots get merged into the previous one


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def probe_duration(p):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)])
    return float(out.stdout.strip())


def video_id(p: Path):
    m = re.search(r"\[([A-Za-z0-9_-]{6,})\]", p.name)
    return m.group(1) if m else re.sub(r"[^A-Za-z0-9_-]", "_", p.stem)[:40]


def make_proxy(src, dst):
    if dst.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src),
         "-vf", "scale=-2:1080,fps=30", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-g", "15", "-keyint_min", "15", "-sc_threshold", "0", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(dst)])


def detect_cuts(p):
    proc = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(p), "-vf", f"select='gt(scene,{SCENE_THRESHOLD})',showinfo",
         "-an", "-f", "null", "-"], capture_output=True, text=True)
    return [float(m.group(1)) for m in re.finditer(r"pts_time:([0-9.]+)", proc.stderr)]


def shots_from_cuts(cuts, dur):
    bounds = [0.0] + [c for c in cuts if 0 < c < dur] + [dur]
    shots = []
    for a, b in zip(bounds, bounds[1:]):
        if shots and (b - a) < MIN_SHOT:
            shots[-1]["end"] = round(b, 3)
            continue
        shots.append({"start": round(a, 3), "end": round(b, 3)})
    return shots


def main():
    dirs = [Path(d) for d in sys.argv[1:]] or [ROOT / "footage" / "official", ROOT / "footage" / "gameplay"]
    cat_file = CAT / "shots.json"
    catalog = json.loads(cat_file.read_text()) if cat_file.exists() else {"videos": {}}
    for d in dirs:
        if not d.exists():
            continue
        for src in sorted(d.glob("*.mp4")):
            vid = video_id(src)
            proxy = PROXY / f"{vid}.mp4"
            print(f"[{vid}] proxy…", flush=True)
            make_proxy(src, proxy)
            dur = probe_duration(proxy)
            prev = catalog["videos"].get(vid, {})
            old_tags = {s["id"]: s for s in prev.get("shots", [])}
            info = src.with_suffix(".info.json")
            title = json.loads(info.read_text()).get("title") if info.exists() else src.stem
            print(f"[{vid}] scene detection…", flush=True)
            shots = shots_from_cuts(detect_cuts(proxy), dur)
            tdir = CAT / "thumbs" / vid
            tdir.mkdir(parents=True, exist_ok=True)
            for i, s in enumerate(shots):
                s["id"] = f"{vid}#{i:03d}"
                s["duration"] = round(s["end"] - s["start"], 3)
                thumb = tdir / f"{i:03d}.jpg"
                if not thumb.exists():
                    mid = s["start"] + s["duration"] / 2
                    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{mid:.3f}", "-i", str(proxy),
                         "-frames:v", "1", "-vf", "scale=384:-2", "-q:v", "4", str(thumb)])
                s["thumb"] = str(thumb.relative_to(ROOT))
                old = old_tags.get(s["id"])
                if old and abs(old["start"] - s["start"]) < 0.05:
                    for k in ("tags", "desc", "vertical_ok", "focus_x", "quality"):
                        if k in old:
                            s[k] = old[k]
            catalog["videos"][vid] = {
                "title": title, "source": str(src.relative_to(ROOT)),
                "proxy": str(proxy.relative_to(ROOT)), "duration": round(dur, 3), "shots": shots,
            }
            make_sheets(vid, shots)
            print(f"[{vid}] {len(shots)} shots", flush=True)
    CAT.mkdir(parents=True, exist_ok=True)
    cat_file.write_text(json.dumps(catalog, indent=1, ensure_ascii=False))
    print(f"catalog -> {cat_file}")


def make_sheets(vid, shots, per_sheet=24, cols=6, w=384, h=216):
    """Tile shot thumbnails with index + timecode labels (Pillow; ffmpeg here lacks drawtext)."""
    from PIL import Image, ImageDraw, ImageFont
    sdir = CAT / "sheets"
    sdir.mkdir(parents=True, exist_ok=True)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 22)
    except OSError:
        font = ImageFont.load_default()
    for k in range(0, len(shots), per_sheet):
        chunk = shots[k:k + per_sheet]
        rows = (len(chunk) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * w, rows * h), "black")
        for j, s in enumerate(chunk):
            im = Image.open(ROOT / s["thumb"]).convert("RGB").resize((w, h))
            d = ImageDraw.Draw(im)
            label = f"{k + j:03d}  {s['start']:.1f}-{s['end']:.1f}s"
            d.rectangle([0, 0, 12 + d.textlength(label, font=font), 30], fill=(0, 0, 0))
            d.text((6, 3), label, font=font, fill=(255, 220, 0))
            sheet.paste(im, ((j % cols) * w, (j // cols) * h))
        sheet.save(sdir / f"{vid}_{k // per_sheet}.jpg", quality=85)


if __name__ == "__main__":
    main()
