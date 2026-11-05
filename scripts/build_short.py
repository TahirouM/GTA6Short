#!/usr/bin/env python3
"""Build a HyperFrames vertical short (1080x1920) from shorts/<slug>/short.json.

Usage: python3 -I scripts/build_short.py shorts/<slug>

short.json:
{
  "handle": "@gta6.actu", "tag": "GTA 6 · ACTU",
  "voice": "assets/audio/voice.mp3", "words": "assets/audio/words.json",
  "emphasis": ["quinze", "PS5"],          # caption words drawn in the accent colour
  "tail": 1.2,                            # seconds held after the last word
  "beats": [
    {"id": "hook", "anchor": null,        # null = 0 s; else first word (from previous beat) starting with this text
     "shots": [{"shot": "QdBZY2fkU-0#001", "in": 0.0, "focus": 0.5, "fit": "cover|frame", "rate": 1.0}],
     "card": {"type": "hook", "big": "J-15", "sub": "AVANT GTA 6"}}
  ]
}
Card types: hook{big,big_html?,kicker?,sub,size?} · headline{kicker,title,chips:[{text,at}],style?:"alert",size?}
            place{kicker,title,sub} · names{items:[{text,at}]} · stat{value,unit,label,sub}
            clock{label,time:"00:00",sub} (slot-machine digits) · cta{title,sub}

Dynamic edit (v2):
  "punch": ["deux jours", ...]   # spoken phrases -> punch-in (scale 1.13) held until next cut + micro shake
  "music": {"src": "assets/audio/bgm.mp3", "from": 12.0, "gain": 0.3, "duck": 0.12}  # auto-ducked under the voice
  "look": "vice" | "none"        # grade + vignette + grain baked into clips (ffmpeg)
  "motion_blur": "on" | "off"    # render-time motion blur on whips/zooms
  beat: "tr": "zoom|glitch|whip|leak|cut" (seam transition, default cycles) · "payoff": true (riser + shake) · "shake": bool
  shot: "tr": "cut|whip" (intra-beat cut)
"""
import html
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
W, H, FPS = 1080, 1920, 30
SFX_LIB = Path.home() / ".claude/skills/media-use/audio/assets/sfx"
PUNCT_ONLY = re.compile(r"^[\s:;?!.,«»\"'…—–-]+$")

COLORS = {"pink": "#FF2E88", "orange": "#FF8A3D", "teal": "#19E3D1", "night": "#0B0614",
          "ink": "#FFFFFF", "yellow": "#FFE14D"}


def esc(s):
    return html.escape(str(s), quote=True)


def norm(w):
    return re.sub(r"[^\w]", "", w.lower())


# ---------------------------------------------------------------- words / timing
def load_words(path):
    raw = json.loads(Path(path).read_text())
    words = []
    for w in raw:
        if PUNCT_ONLY.match(w["text"]) and words:  # French " :" " ?" -> glue to previous word
            words[-1]["text"] += w["text"].strip()
            words[-1]["end"] = max(words[-1]["end"], w["end"])
            continue
        words.append(dict(w))
    return words


def resolve_anchor(words, text, after_t):
    """First occurrence (at/after after_t) of a word or multi-word phrase; returns its start time."""
    keys = [norm(k) for k in text.split()]
    for i, w in enumerate(words):
        if w["start"] < after_t - 1e-3:
            continue
        seq = [norm(x["text"]) for x in words[i:i + len(keys)]]
        if len(seq) == len(keys) and all(a == b or (j == len(keys) - 1 and a.startswith(b))
                                         for j, (a, b) in enumerate(zip(seq, keys))):
            return w["start"]
    raise SystemExit(f"anchor introuvable: {text!r} après {after_t:.2f}s")


# ---------------------------------------------------------------- footage
def load_catalog():
    cat = json.loads((ROOT / "catalog/shots.json").read_text())
    return {s["id"]: (v, s) for v in cat["videos"].values() for s in v["shots"]}


def active_area(proxy):
    """Letterbox-free area (w, h, x, y) of a proxy, cached in catalog/active.json."""
    cache_f = ROOT / "catalog/active.json"
    cache = json.loads(cache_f.read_text()) if cache_f.exists() else {}
    if proxy not in cache:
        p = subprocess.run(["ffmpeg", "-v", "info", "-i", str(ROOT / proxy), "-vf",
                            "fps=1,cropdetect=limit=24:round=2:reset=0", "-an", "-f", "null", "-"],
                           capture_output=True, text=True)
        found = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", p.stderr)
        best = max(set(found), key=found.count) if found else ("1920", "1080", "0", "0")
        w, h, x, y = map(int, best)
        if w < 1700:  # pillarbox detections from dark frames: keep full width
            w, x = 1920, 0
        cache[proxy] = [w, h, x, y]
        cache_f.write_text(json.dumps(cache, indent=1))
    return cache[proxy]


def cut_clip(short_dir, shots, spec, dur, idx):
    vid, shot = shots[spec["shot"]]
    rate = spec.get("rate", 1.0)
    src_in = shot["start"] + spec.get("in", 0.0)
    avail = shot["end"] - src_in - 0.04
    if dur * rate > avail:  # auto slow-mo instead of spilling into the next source shot
        rate = max(0.5, avail / dur)
    need = dur * rate
    if need > avail + 0.05:
        print(f"  ! {spec['shot']}: besoin {need:.2f}s même à 0.5x, dispo {avail:.2f}s → choisir un plan plus long")
    focus = spec.get("focus", shot.get("focus_x", 0.5))
    fit = spec.get("fit", "cover")
    name = f"c{idx:02d}_{spec['shot'].replace('#', '_')}_{fit}.mp4"
    out = short_dir / "assets/clips" / name
    out.parent.mkdir(parents=True, exist_ok=True)
    aw, ah, ax, ay = active_area(vid["proxy"])
    cw = int(round(ah * 9 / 16 / 2) * 2)
    x = ax + int(round(focus * (aw - cw)))
    # "vice" look baked into the clip (contract: grades/grain/vignette on footage never as CSS filters)
    look = (",eq=contrast=1.07:saturation=1.16:gamma=0.98,colorbalance=rs=0.03:bs=0.02:rh=0.02:bh=-0.03,"
            "vignette=angle=PI/5,noise=c0s=6:c0f=t+u") if spec.get("look", "vice") == "vice" else ""
    if fit == "frame":  # 16:9 window over a blurred, darkened cover
        vf = (f"setpts=PTS/{rate},split[a][b];"
              f"[a]crop={cw}:{ah}:{x}:{ay},scale={W}:{H},gblur=sigma=28,eq=brightness=-0.12:saturation=1.2[bg];"
              f"[b]crop={aw}:{ah}:{ax}:{ay},scale={W}:-2[fg];[bg][fg]overlay=0:(H-h)/2-140{look},fps={FPS}")
    else:
        vf = f"setpts=PTS/{rate},crop={cw}:{ah}:{x}:{ay},setsar=1,scale={W}:{H}:flags=lanczos,unsharp=5:5:0.6{look},fps={FPS}"
    if not out.exists():
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{src_in:.3f}", "-i", str(ROOT / vid["proxy"]),
                        "-t", f"{need + 0.2:.3f}", "-filter_complex", vf, "-an", "-c:v", "libx264",
                        "-preset", "medium", "-crf", "19", "-g", "15", "-pix_fmt", "yuv420p",
                        "-movflags", "+faststart", str(out)], check=True)
    return f"assets/clips/{name}"


# ---------------------------------------------------------------- shared style
BASE_CSS = """
:root{--pink:%(pink)s;--orange:%(orange)s;--teal:%(teal)s;--night:%(night)s;--ink:%(ink)s;--yellow:%(yellow)s;}
""" % COLORS


def scene(cid, dur, body, css, js):
    return f"""<template>
  <style>
    {BASE_CSS}
    #root {{ position:absolute; inset:0; font-family:'Archivo Black',sans-serif; color:var(--ink); }}
    {css}
  </style>
  <div id="root" data-composition-id="{cid}" data-width="{W}" data-height="{H}">
{body}
  </div>
  <script>
    const tl = gsap.timeline({{ paused: true }});
{js}
    window.__timelines["{cid}"] = tl;
  </script>
</template>
"""


def exit_js(sel, dur, d=0.22):
    return (f'    tl.to("{sel}", {{ opacity: 0, filter: "blur(10px)", duration: {d}, ease: "power3.in" }}, {dur - d - 0.04:.3f});\n')


def chroma_js(sel, at, d=0.32, px=14):
    """RGB-split on text: teal/pink offset copies collapsing onto the glyphs (text-shadow, seek-safe)."""
    return (f'    tl.fromTo("{sel}", {{ textShadow: "-{px}px 0 0 rgba(25,227,209,.9), {px}px 0 0 rgba(255,46,136,.9)" }}, '
            f'{{ textShadow: "0px 0 0 rgba(25,227,209,0), 0px 0 0 rgba(255,46,136,0)", duration: {d}, ease: "expo.out" }}, {at:.3f});\n')


# Safe zone shared by TikTok, Reels and Shorts (1080x1920): text never under the right-hand rail,
# the top bars or the bottom caption/handle area. Every card lives in a fixed .wrap box of exactly
# this size so `hyperframes check` reports any text that overflows it (text_box_overflow).
SAFE_L, SAFE_W, CARD_TOP, CARD_H = 60, 900, 310, 780     # cards: x 60..960, y 310..1090
CAP_TOP, CAP_H = 1110, 220                                # captions: y 1110..1330
WRAP_CSS = f"position:absolute; left:{SAFE_L}px; width:{SAFE_W}px; top:{CARD_TOP}px; height:{CARD_H}px;"


def fit(text, base, k=0.8, width=SAFE_W, longest_word=False):
    """Font size so the (longest word of the) text fits the safe width; k = average glyph advance in em."""
    unit = max(text.split(), key=len) if longest_word else text
    return int(min(base, width / max(1, len(unit) * k)))


def md_background(cid):
    """Pure motion-design ground (no footage): night gradient, sun, synthwave floor grid scrolling."""
    body = f"""    <div class="mdbg" id="{cid}-bg" aria-hidden="true" data-layout-allow-overflow><div class="sun"></div><div class="floor"><div class="grid" id="{cid}-grid"></div></div></div>"""
    css = f"""
    #{cid}-bg {{ position:absolute; inset:0; overflow:hidden; background:linear-gradient(180deg,#0B0614 0%,#2A0B3D 48%,#5B1252 62%,#0B0614 100%); }}
    #{cid}-bg .sun {{ position:absolute; left:290px; top:1020px; width:500px; height:500px; border-radius:50%;
      background:linear-gradient(180deg,#FFE14D,#FF8A3D 45%,#FF2E88); box-shadow:0 0 120px rgba(255,46,136,.6);
      -webkit-mask:repeating-linear-gradient(180deg,#000 0 26px,transparent 26px 34px); }}
    #{cid}-bg .floor {{ position:absolute; left:-600px; right:-600px; top:1240px; height:900px; perspective:420px; overflow:hidden; }}
    #{cid}-bg .grid {{ position:absolute; inset:-400px 0 0 0; transform-origin:50% 0; transform:rotateX(62deg);
      background-image:linear-gradient(rgba(25,227,209,.75) 3px,transparent 3px),linear-gradient(90deg,rgba(255,46,136,.7) 3px,transparent 3px);
      background-size:120px 120px; }}"""
    return body, css


def md_grid_js(cid, dur):
    return f'    tl.fromTo("#{cid}-grid", {{ backgroundPositionY: "0px" }}, {{ backgroundPositionY: "{int(dur * 240)}px", duration: {dur:.3f}, ease: "none" }}, 0);\n'


def card_hook(cid, c, dur, rel):
    """Visible on frame 0 (thumbnail = hook): starts big and sharp, settles with an RGB split."""
    big = esc(c["big"])
    low = c.get("pos") == "low"
    body = f"""    <div class="wrap" id="{cid}-wrap">
      <div class="kick" id="{cid}-kick">{esc(c.get('kicker', ''))}</div>
      <div class="big" id="{cid}-big">{c.get('big_html') or big}</div>
      <div class="sub" id="{cid}-sub">{''.join(f'<span class="w">{esc(w)}</span> ' for w in c.get('sub', '').split())}</div>
    </div>"""
    css = f"""
    #{cid}-wrap {{ {WRAP_CSS} display:flex; flex-direction:column; align-items:center; justify-content:{'flex-end' if low else 'flex-start'}; text-align:center; }}
    #{cid}-kick {{ display:{'inline-block' if c.get('kicker') else 'none'}; font-size:{fit(c.get('kicker', ''), 46, 0.78)}px; background:var(--yellow); color:var(--night);
      padding:10px 24px 6px; letter-spacing:.05em; transform:rotate(-2deg); margin-bottom:14px; }}
    #{cid}-big {{ font-size:{fit(c['big'], c.get('size', 250), 0.74, SAFE_W - 30)}px; line-height:.9; color:var(--ink); letter-spacing:-.02em; white-space:nowrap;
      -webkit-text-stroke:8px var(--night); paint-order:stroke fill; }}
    #{cid}-big .u {{ color:var(--pink); }}
    #{cid}-sub {{ margin-top:22px; font-size:{fit(c.get('sub', ''), 84, 0.8, SAFE_W - 20)}px; line-height:1; text-transform:uppercase;
      -webkit-text-stroke:7px var(--night); paint-order:stroke fill; text-shadow:0 6px 24px rgba(0,0,0,.7); }}
    #{cid}-sub .w {{ display:inline-block; }}"""
    js = (f'    tl.fromTo("#{cid}-big", {{ scale: 1.06 }}, {{ scale: 1, duration: 0.45, ease: "expo.out" }}, 0.0);\n'
          + chroma_js(f"#{cid}-big", 0.0, 0.5, 12)
          + f'    tl.fromTo("#{cid}-sub .w", {{ opacity: 0, filter: "blur(6px)" }}, '
          f'{{ opacity: 1, filter: "blur(0px)", duration: 0.13, stagger: 0.07, ease: "power2.out" }}, 0.3);\n'
          + exit_js(f"#{cid}-wrap", dur))
    return body, css, js, [("impact-bass-1", 0.0)]


def card_clock(cid, c, dur, rel):
    """Slot-machine time: each digit spins through a strip and lands on its target."""
    t = c.get("time", "00:00")
    cols, js = [], ""
    for i, ch in enumerate(t):
        if not ch.isdigit():
            cols.append(f'<span class="sep">{esc(ch)}</span>')
            continue
        strip = [str((int(ch) + k) % 10) for k in range(1, 10 + 2 * i)] + [ch]
        cols.append(f'<span class="dg"><span class="strip" id="{cid}-d{i}">' + "".join(f"<b>{d}</b>" for d in strip) + "</span></span>")
        js += (f'    tl.fromTo("#{cid}-d{i}", {{ yPercent: 0 }}, {{ yPercent: {-100 * (len(strip) - 1) / len(strip):.4f}, '
               f'duration: {0.7 + 0.12 * i:.2f}, ease: "expo.out" }}, 0.05);\n')
    body = f"""    <div class="wrap" id="{cid}-wrap">
      <div class="label" id="{cid}-label">{esc(c.get('label', ''))}</div>
      <div class="clock" id="{cid}-clock" aria-hidden="true" data-layout-allow-overflow data-layout-allow-overlap>{''.join(cols)}</div>
      <div class="sub" id="{cid}-sub">{esc(c.get('sub', ''))}</div>
    </div>"""
    css = f"""
    #{cid}-wrap {{ {WRAP_CSS} text-align:center; }}
    #{cid}-label {{ display:inline-block; font-size:{fit(c.get('label', ''), 64, 0.78, SAFE_W - 60)}px; color:var(--ink); background:var(--pink); padding:10px 28px 4px; transform:rotate(-2deg); }}
    #{cid}-clock {{ margin-top:26px; display:inline-flex; align-items:center; gap:6px; padding:18px 30px; border-radius:28px;
      background:rgba(11,6,20,.82); border:5px solid var(--teal); box-shadow:0 0 60px rgba(25,227,209,.35); }}
    #{cid}-clock .dg {{ display:inline-block; height:220px; overflow:hidden; font-size:220px; line-height:220px; width:150px; }}
    #{cid}-clock .strip {{ display:flex; flex-direction:column; }}
    #{cid}-clock .strip b {{ display:block; height:220px; font-weight:400; color:var(--yellow); }}
    #{cid}-clock .sep {{ font-size:190px; line-height:220px; color:var(--teal); }}
    #{cid}-sub {{ margin-top:22px; font-family:'Inter',sans-serif; font-weight:900; font-size:50px; letter-spacing:.06em; text-transform:uppercase;
      text-shadow:0 4px 18px rgba(0,0,0,.8); }}"""
    js = (f'    tl.fromTo("#{cid}-label", {{ opacity: 0, x: -60 }}, {{ opacity: 1, x: 0, duration: 0.3, ease: "expo.out" }}, 0.0);\n'
          f'    tl.fromTo("#{cid}-clock", {{ opacity: 0, scale: 0.8 }}, {{ opacity: 1, scale: 1, duration: 0.35, ease: "back.out(1.6)" }}, 0.02);\n'
          + js
          + f'    tl.fromTo("#{cid}-sub", {{ opacity: 0, y: 20 }}, {{ opacity: 1, y: 0, duration: 0.3, ease: "expo.out" }}, 0.9);\n'
          + exit_js(f"#{cid}-wrap", dur))
    n = sum(ch.isdigit() for ch in t)
    return body, css, js, [("click-soft", 0.75 + 0.12 * k) for k in range(n)][::2] + [("impact-bass-2", 0.0)]


def card_headline(cid, c, dur, rel):
    chips = c.get("chips", [])
    alert = c.get("style") == "alert"
    chip_html = "".join(f'<span class="chip" id="{cid}-chip{i}">{esc(ch["text"])}</span>' for i, ch in enumerate(chips))
    body = f"""    <div class="wrap" id="{cid}-wrap">
      <div class="kicker" id="{cid}-kicker">{esc(c.get('kicker', ''))}</div>
      <div class="title" id="{cid}-title">{esc(c['title'])}</div>
      <div class="chips">{chip_html}</div>
    </div>"""
    tsize = fit(c["title"], c.get("size", 170 if alert else 200), 0.82, SAFE_W - 20, longest_word=True)
    css = f"""
    #{cid}-wrap {{ {WRAP_CSS} }}
    #{cid}-kicker {{ display:inline-block; background:var(--teal); color:var(--night); font-size:40px; padding:8px 20px 6px; border-radius:6px; letter-spacing:.04em; }}
    #{cid}-title {{ margin-top:14px; font-size:{tsize}px; line-height:.9; text-transform:uppercase; color:var(--ink);
      text-shadow:0 0 0 transparent, 8px 8px 0 var(--pink); }}
    #{cid}-wrap .chips {{ margin-top:34px; display:flex; gap:18px; flex-wrap:wrap; }}
    #{cid}-wrap .chip {{ display:inline-block; font-size:{min(52, min(fit(ch['text'], 52, 0.8, SAFE_W - 70) for ch in chips) if chips else 52)}px; padding:14px 26px 10px; border-radius:999px;
      background:rgba(11,6,20,.8); border:4px solid var(--pink); color:var(--ink); white-space:nowrap; }}"""
    if alert:  # hazard kicker, yellow title
        css += f"""
    #{cid}-kicker {{ background:repeating-linear-gradient(-45deg,var(--yellow) 0 22px,var(--night) 22px 44px); color:var(--ink);
      font-size:46px; padding:10px 26px 6px; -webkit-text-stroke:8px var(--night); paint-order:stroke fill; }}
    #{cid}-title {{ color:var(--yellow); -webkit-text-stroke:7px var(--night); paint-order:stroke fill; text-shadow:none; }}
    #{cid}-wrap .chip {{ border-color:var(--yellow); }}"""
    js = (f'    tl.fromTo("#{cid}-kicker", {{ opacity: 0, x: -40 }}, {{ opacity: 1, x: 0, duration: 0.35, ease: "expo.out" }}, 0.0);\n'
          f'    tl.fromTo("#{cid}-title", {{ opacity: 0, scale: 1.25, filter: "blur(12px)" }}, '
          f'{{ opacity: 1, scale: 1, filter: "blur(0px)", duration: 0.4, ease: "expo.out" }}, 0.08);\n'
          + (chroma_js(f"#{cid}-title", 0.08, 0.45) if alert else ""))
    sfx = [("whoosh-short", 0.08)]
    for i, ch in enumerate(chips):
        t = max(0.3, rel(ch["at"])) if ch.get("at") else 0.45 + i * 0.12
        js += (f'    tl.fromTo("#{cid}-chip{i}", {{ opacity: 0, scale: 0.6, y: 20 }}, '
               f'{{ opacity: 1, scale: 1, y: 0, duration: 0.32, ease: "back.out(1.6)" }}, {t:.3f});\n')
        sfx.append(("pop", t))
    js += exit_js(f"#{cid}-wrap", dur)
    return body, css, js, sfx


def card_place(cid, c, dur, rel):
    body = f"""    <div class="wrap" id="{cid}-wrap">
      <div class="kicker" id="{cid}-kicker"><span class="pin"></span>{esc(c.get('kicker', ''))}</div>
      <div class="title" id="{cid}-title">{''.join(f'<span class="w">{esc(w)}</span> ' for w in c['title'].split())}</div>
      <div class="sub" id="{cid}-sub">{esc(c.get('sub', ''))}</div>
    </div>"""
    css = f"""
    #{cid}-wrap {{ {WRAP_CSS} }}
    #{cid}-kicker {{ font-size:{fit(c.get('kicker', ''), 44, 0.74, SAFE_W - 60)}px; color:var(--teal); letter-spacing:.06em; display:flex; align-items:center; gap:16px; white-space:nowrap; }}
    #{cid}-kicker .pin {{ flex:none; width:34px; height:34px; border-radius:50% 50% 50% 0; background:var(--pink); transform:rotate(-45deg); display:inline-block; }}
    #{cid}-title {{ margin-top:10px; font-size:{fit(c['title'], c.get('size', 170), 0.84, SAFE_W - 20, longest_word=True)}px; line-height:.88; text-transform:uppercase;
      filter:drop-shadow(0 8px 0 var(--night)); }}
    #{cid}-title .w {{ display:inline-block; background:linear-gradient(180deg,var(--yellow),var(--orange) 55%,var(--pink));
      -webkit-background-clip:text; background-clip:text; -webkit-text-fill-color:transparent; padding:0 4px; }}
    #{cid}-sub {{ margin-top:18px; font-family:'Inter',sans-serif; font-weight:900; font-size:50px; text-shadow:0 4px 18px rgba(0,0,0,.8); }}"""
    js = (f'    tl.fromTo("#{cid}-kicker", {{ opacity: 0, y: -20 }}, {{ opacity: 1, y: 0, duration: 0.3, ease: "expo.out" }}, 0.0);\n'
          f'    tl.fromTo("#{cid}-title .w", {{ opacity: 0, y: 60, filter: "blur(8px)" }}, '
          f'{{ opacity: 1, y: 0, filter: "blur(0px)", duration: 0.38, stagger: 0.1, ease: "expo.out" }}, 0.1);\n'
          f'    tl.fromTo("#{cid}-sub", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.25, ease: "power2.out" }}, 0.55);\n'
          + exit_js(f"#{cid}-wrap", dur))
    return body, css, js, [("whoosh", 0.1)]


def card_names(cid, c, dur, rel):
    items = c["items"]
    low = c.get("pos") == "low"
    body = (f'    <div class="wrap" id="{cid}-wrap">\n' + "\n".join(
        f'      <div class="tag {"l" if i % 2 == 0 else "r"}" id="{cid}-n{i}"><span class="bar"></span>{esc(it["text"])}</div>'
        for i, it in enumerate(items)) + "\n    </div>")
    size = min(fit(it["text"], 120, 0.8, SAFE_W - 120) for it in items)
    css = f"""
    #{cid}-wrap {{ {WRAP_CSS} display:flex; flex-direction:column; justify-content:{'flex-end' if low else 'flex-start'}; gap:30px; }}
    #{cid}-wrap .tag {{ position:relative; align-self:flex-start; font-size:{size}px; line-height:1; text-transform:uppercase; padding:10px 34px 4px 44px;
      background:var(--night); color:var(--ink); box-shadow:10px 10px 0 var(--pink); white-space:nowrap; }}
    #{cid}-wrap .tag .bar {{ position:absolute; left:0; top:0; bottom:0; width:14px; background:var(--teal); }}
    #{cid}-wrap .tag.r {{ align-self:flex-end; margin-right:12px; box-shadow:-10px 10px 0 var(--orange); }}"""
    js, sfx = "", []
    for i, it in enumerate(items):
        t = max(0.0, rel(it["at"])) if it.get("at") else i * 0.35
        dx = -260 if i % 2 == 0 else 260
        js += (f'    tl.fromTo("#{cid}-n{i}", {{ opacity: 0, x: {dx}, filter: "blur(10px)" }}, '
               f'{{ opacity: 1, x: 0, filter: "blur(0px)", duration: 0.34, ease: "expo.out" }}, {t:.3f});\n')
        sfx.append(("whoosh-short" if i % 2 == 0 else "whoosh", t))
    js += exit_js(f"#{cid}-wrap", dur)
    return body, css, js, sfx


def card_stat(cid, c, dur, rel):
    val = int(c["value"])
    body = f"""    <div class="wrap" id="{cid}-wrap">
      <div class="label" id="{cid}-label">{esc(c.get('label', ''))}</div>
      <div class="num"><span id="{cid}-val">0</span><span class="unit">{esc(c.get('unit', ''))}</span></div>
      <div class="sub" id="{cid}-sub">{esc(c.get('sub', ''))}</div>
    </div>"""
    css = f"""
    #{cid}-wrap {{ {WRAP_CSS} text-align:center; }}
    #{cid}-label {{ display:inline-block; font-size:42px; background:var(--pink); padding:8px 22px 6px; border-radius:6px; letter-spacing:.05em; }}
    #{cid}-wrap .num {{ font-size:{fit(str(val) + c.get('unit', ''), 300, 0.7, SAFE_W - 40)}px; line-height:.95; color:var(--ink); -webkit-text-stroke:8px var(--night); paint-order:stroke fill;
      text-shadow:0 0 50px rgba(25,227,209,.45); white-space:nowrap; }}
    #{cid}-wrap .unit {{ font-size:.36em; color:var(--teal); margin-left:12px; }}
    #{cid}-sub {{ display:inline-block; margin-top:10px; font-family:'Inter',sans-serif; font-weight:900; font-size:{fit(c.get('sub', ''), 46, 0.72, SAFE_W - 60)}px; text-transform:uppercase; letter-spacing:.04em;
      background:rgba(11,6,20,.78); padding:12px 26px; border-radius:12px; }}"""
    v = cid.replace("-", "_")
    js = (f'    tl.fromTo("#{cid}-wrap", {{ opacity: 0, scale: 0.9 }}, {{ opacity: 1, scale: 1, duration: 0.35, ease: "expo.out" }}, 0.0);\n'
          f'    const {v}_n = {{ v: 0 }};\n'
          f'    tl.fromTo({v}_n, {{ v: 0 }}, {{ v: {val}, duration: 0.9, ease: "power3.out", '
          f'onUpdate: () => {{ document.querySelector("#{cid}-val").textContent = Math.round({v}_n.v); }} }}, 0.1);\n'
          f'    tl.fromTo("#{cid}-sub", {{ opacity: 0, y: 20 }}, {{ opacity: 1, y: 0, duration: 0.3, ease: "expo.out" }}, 0.7);\n'
          + exit_js(f"#{cid}-wrap", dur))
    return body, css, js, [("whoosh", 0.0), ("ping", 1.0)]


def card_storage(cid, c, dur, rel):
    """Pure motion design: a console storage gauge filling up to the game's size."""
    used, total = float(c["used"]), float(c["total"])
    pct = used / total * 100
    bg_body, bg_css = md_background(cid)
    body = bg_body + f"""
    <div class="wrap" id="{cid}-wrap">
      <div class="label" id="{cid}-label">{esc(c.get('label', ''))}</div>
      <div class="dev" id="{cid}-dev">{esc(c.get('device', ''))}</div>
      <div class="gauge"><div class="fill" id="{cid}-fill"></div><div class="mark" id="{cid}-mark"></div></div>
      <div class="scale"><span>0</span><span>{esc(c.get('total_label', f"{int(total)} Go"))}</span></div>
      <div class="num"><span id="{cid}-val">0</span><span class="u"> Go</span></div>
      <div class="sub" id="{cid}-sub">{esc(c.get('sub', ''))}</div>
    </div>"""
    css = bg_css + f"""
    #{cid}-wrap {{ {WRAP_CSS} text-align:center; }}
    #{cid}-label {{ display:inline-block; font-size:{fit(c.get('label', ''), 46, 0.78, SAFE_W - 60)}px; background:var(--teal); color:var(--night); padding:10px 26px 6px; letter-spacing:.05em; }}
    #{cid}-dev {{ margin-top:30px; font-size:{fit(c.get('device', ''), 110, 0.8, SAFE_W - 20)}px; line-height:1; text-transform:uppercase; -webkit-text-stroke:6px var(--night); paint-order:stroke fill; }}
    #{cid}-wrap .gauge {{ position:relative; margin:44px auto 0; width:840px; height:120px; border-radius:24px; border:6px solid var(--ink);
      background:rgba(11,6,20,.75); overflow:hidden; box-shadow:0 0 50px rgba(25,227,209,.35); }}
    #{cid}-fill {{ position:absolute; left:0; top:0; bottom:0; width:100%; transform-origin:0 50%;
      background:repeating-linear-gradient(-45deg,var(--pink) 0 26px,#ff5aa4 26px 52px); }}
    #{cid}-mark {{ position:absolute; top:-6px; bottom:-6px; left:{pct:.2f}%; width:6px; background:var(--yellow); }}
    #{cid}-wrap .scale {{ width:840px; margin:12px auto 0; display:flex; justify-content:space-between; font-family:'Inter',sans-serif; font-weight:900; font-size:36px; opacity:.85; }}
    #{cid}-wrap .num {{ margin-top:24px; font-size:200px; line-height:1; color:var(--yellow); -webkit-text-stroke:8px var(--night); paint-order:stroke fill; white-space:nowrap; }}
    #{cid}-wrap .num .u {{ font-size:90px; color:var(--ink); }}
    #{cid}-sub {{ margin-top:16px; display:inline-block; font-family:'Inter',sans-serif; font-weight:900; font-size:{fit(c.get('sub', ''), 48, 0.66, SAFE_W - 70)}px; text-transform:uppercase;
      background:var(--ink); color:var(--night); padding:12px 26px; border-radius:14px; }}"""
    v = cid.replace("-", "_")
    js = (md_grid_js(cid, dur)
          + f'    tl.fromTo("#{cid}-bg", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.2, ease: "power2.out" }}, 0);\n'
          f'    tl.fromTo("#{cid}-label", {{ opacity: 0, y: -30 }}, {{ opacity: 1, y: 0, duration: 0.3, ease: "expo.out" }}, 0.05);\n'
          f'    tl.fromTo("#{cid}-dev", {{ opacity: 0, scale: 1.2, filter: "blur(8px)" }}, {{ opacity: 1, scale: 1, filter: "blur(0px)", duration: 0.35, ease: "expo.out" }}, 0.12);\n'
          f'    tl.fromTo("#{cid}-fill", {{ scaleX: 0 }}, {{ scaleX: {pct / 100:.4f}, duration: 1.1, ease: "power3.inOut" }}, 0.35);\n'
          f'    const {v}_n = {{ v: 0 }};\n'
          f'    tl.fromTo({v}_n, {{ v: 0 }}, {{ v: {int(used)}, duration: 1.1, ease: "power3.inOut", '
          f'onUpdate: () => {{ document.querySelector("#{cid}-val").textContent = Math.round({v}_n.v); }} }}, 0.35);\n'
          f'    tl.fromTo("#{cid}-sub", {{ opacity: 0, y: 30 }}, {{ opacity: 1, y: 0, duration: 0.35, ease: "back.out(1.6)" }}, 1.4);\n'
          + exit_js(f"#{cid}-wrap", dur))
    return body, css, js, [("riser", -1), ("pop", 1.45)] if False else [("whoosh", 0.0), ("typing", 0.4), ("ping", 1.45)]


def card_timeline(cid, c, dur, rel):
    """Pure motion design: vertical date rail; each date lights up on its spoken anchor."""
    items = c["items"]
    bg_body, bg_css = md_background(cid)
    rows = "\n".join(
        f'      <div class="row" id="{cid}-r{i}"><span class="dot"></span><span class="d">{esc(it["date"])}</span><span class="t">{esc(it["text"])}</span></div>'
        for i, it in enumerate(items))
    body = bg_body + f"""
    <div class="wrap" id="{cid}-wrap">
      <div class="label" id="{cid}-label">{esc(c.get('label', ''))}</div>
      <div class="rail"><div class="line" id="{cid}-line"></div>
{rows}
      </div>
    </div>"""
    tsize = min(fit(it["text"], 54, 0.72, SAFE_W - 70 - 330 - 40) for it in items)
    css = bg_css + f"""
    #{cid}-wrap {{ {WRAP_CSS} }}
    #{cid}-label {{ display:inline-block; font-size:{fit(c.get('label', ''), 48, 0.78, SAFE_W - 60)}px; background:var(--pink); padding:10px 26px 6px; transform:rotate(-2deg); }}
    #{cid}-wrap .rail {{ position:relative; margin-top:40px; padding-left:70px; }}
    #{cid}-line {{ position:absolute; left:22px; top:30px; bottom:30px; width:8px; border-radius:4px; background:linear-gradient(180deg,var(--teal),var(--pink)); transform-origin:50% 0; }}
    #{cid}-wrap .row {{ position:relative; display:flex; align-items:baseline; gap:26px; height:150px; opacity:.35; }}
    #{cid}-wrap .row .dot {{ position:absolute; left:-62px; top:38px; width:36px; height:36px; border-radius:50%; background:var(--night); border:6px solid var(--teal); }}
    #{cid}-wrap .row .d {{ flex:none; width:330px; font-size:82px; line-height:1; color:var(--ink); -webkit-text-stroke:6px var(--night); paint-order:stroke fill; white-space:nowrap; }}
    #{cid}-wrap .row .t {{ font-family:'Inter',sans-serif; font-weight:900; font-size:{tsize}px; text-transform:uppercase; white-space:nowrap; }}
    #{cid}-wrap .row.hot .d {{ color:var(--yellow); }}"""
    js = (md_grid_js(cid, dur)
          + f'    tl.fromTo("#{cid}-bg", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.2, ease: "power2.out" }}, 0);\n'
          f'    tl.fromTo("#{cid}-label", {{ opacity: 0, x: -50 }}, {{ opacity: 1, x: 0, duration: 0.3, ease: "expo.out" }}, 0.05);\n'
          f'    tl.fromTo("#{cid}-line", {{ scaleY: 0 }}, {{ scaleY: 1, duration: 0.6, ease: "power3.out" }}, 0.1);\n'
          f'    tl.fromTo("#{cid}-wrap .row", {{ x: -40 }}, {{ x: 0, duration: 0.4, stagger: 0.08, ease: "expo.out" }}, 0.15);\n')
    sfx = [("whoosh", 0.0)]
    for i, it in enumerate(items):
        if not (it.get("at") or it.get("lit")):
            continue  # stays dimmed: a date still to come
        t = max(0.2, rel(it["at"])) if it.get("at") else 0.35 + 0.12 * i
        js += (f'    tl.fromTo("#{cid}-r{i}", {{ opacity: 0.35, scale: 1 }}, {{ opacity: 1, scale: 1.04, duration: 0.25, ease: "back.out(2)" }}, {t:.3f});\n'
               f'    tl.fromTo("#{cid}-r{i} .dot", {{ backgroundColor: "#0B0614", scale: 1 }}, {{ backgroundColor: "#FF2E88", scale: 1.25, duration: 0.2, ease: "back.out(3)" }}, {t:.3f});\n'
               f'    tl.fromTo("#{cid}-r{i} .d", {{ color: "#FFFFFF" }}, {{ color: "#FFE14D", duration: 0.15 }}, {t:.3f});\n')
        if it.get("at"):
            sfx.append(("pop", t))
    js += exit_js(f"#{cid}-wrap", dur)
    return body, css, js, sfx


def card_stamp(cid, c, dur, rel):
    """Rubber stamp slammed onto the frame (a denial / a 'no')."""
    body = f"""    <div class="wrap" id="{cid}-wrap">
      <div class="stamp" id="{cid}-stamp"><div class="t">{esc(c['title'])}</div></div>
      <div class="sub" id="{cid}-sub">{esc(c.get('sub', ''))}</div>
    </div>"""
    css = f"""
    #{cid}-wrap {{ {WRAP_CSS} display:flex; flex-direction:column; align-items:center; justify-content:center; text-align:center; }}
    #{cid}-stamp {{ width:820px; padding:26px 30px 18px; border:12px double #FF3B5C; border-radius:22px; transform:rotate(-7deg);
      background:rgba(11,6,20,.55); box-shadow:0 0 0 4px rgba(255,59,92,.25); }}
    #{cid}-stamp .t {{ font-size:{fit(c['title'], 130, 0.8, 740, longest_word=True)}px; line-height:.92; text-transform:uppercase; color:#FF3B5C;
      -webkit-text-stroke:4px var(--night); paint-order:stroke fill; }}
    #{cid}-sub {{ margin-top:46px; display:inline-block; font-family:'Inter',sans-serif; font-weight:900; font-size:{fit(c.get('sub', ''), 52, 0.66, SAFE_W - 70)}px; text-transform:uppercase;
      background:var(--ink); color:var(--night); padding:14px 28px; border-radius:14px; }}"""
    js = (f'    tl.fromTo("#{cid}-stamp", {{ opacity: 0, scale: 2.4, rotation: -16 }}, {{ opacity: 1, scale: 1, rotation: -7, duration: 0.28, ease: "power4.in" }}, 0.0);\n'
          f'    tl.fromTo("#{cid}-sub", {{ opacity: 0, y: 30 }}, {{ opacity: 1, y: 0, duration: 0.3, ease: "expo.out" }}, 0.5);\n'
          + exit_js(f"#{cid}-wrap", dur))
    return body, css, js, [("impact-bass-1", 0.26)]


def card_cta(cid, c, dur, rel):
    body = f"""    <div class="wrap" id="{cid}-wrap">
      <div class="title" id="{cid}-title">{esc(c['title']).replace(' ?', '&nbsp;?')}</div>
      <div class="sub" id="{cid}-sub">{esc(c.get('sub', ''))}</div>
    </div>"""
    css = f"""
    #{cid}-wrap {{ {WRAP_CSS} padding-top:60px; text-align:center; }}
    #{cid}-title {{ font-size:{fit(c['title'].replace(' ?', '?'), 170, 0.8, SAFE_W - 40, longest_word=True)}px; line-height:.9; text-transform:uppercase; color:var(--yellow);
      -webkit-text-stroke:7px var(--night); paint-order:stroke fill; text-shadow:10px 10px 0 var(--pink); }}
    #{cid}-sub {{ margin-top:30px; display:inline-block; font-family:'Inter',sans-serif; font-weight:900; font-size:{fit(c.get('sub', ''), 52, 0.6, SAFE_W - 70)}px;
      background:var(--ink); color:var(--night); padding:16px 30px; border-radius:16px; }}"""
    js = (f'    tl.fromTo("#{cid}-title", {{ opacity: 0, scale: 0.7, rotation: -4 }}, '
          f'{{ opacity: 1, scale: 1, rotation: 0, duration: 0.5, ease: "back.out(1.5)" }}, 0.0);\n'
          f'    tl.fromTo("#{cid}-sub", {{ opacity: 0, y: 40 }}, {{ opacity: 1, y: 0, duration: 0.35, ease: "expo.out" }}, 0.35);\n')
    return body, css, js, [("impact-bass-2", 0.0), ("pop", 0.35)]


CARDS = {"hook": card_hook, "headline": card_headline, "place": card_place, "clock": card_clock,
         "names": card_names, "stat": card_stat, "cta": card_cta,
         "storage": card_storage, "timeline": card_timeline, "stamp": card_stamp}
MD_CARDS = {"storage", "timeline"}  # full-screen motion design: the beat needs no footage


# ---------------------------------------------------------------- captions
def caption_groups(words, max_words=3, max_chars=16):
    groups, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        txt = " ".join(x["text"] for x in cur)
        brk = (nxt is None or len(cur) >= max_words or re.search(r"[.,?!:;]$", w["text"])
               or (nxt and nxt["start"] - w["end"] >= 0.15) or len(txt + " " + (nxt["text"] if nxt else "")) > max_chars)
        if brk:
            groups.append(cur)
            cur = []
    return groups


def build_captions(words, total, emphasis):
    emph = {norm(e) for e in emphasis}
    groups = caption_groups(words)
    body, js = [], []
    for gi, g in enumerate(groups):
        start = max(0.15, g[0]["start"] - 0.04)
        nxt = groups[gi + 1][0]["start"] - 0.04 if gi + 1 < len(groups) else total - 0.3
        end = max(g[-1]["end"] + 0.12, start + 0.4)
        end = min(end if gi + 1 < len(groups) else total - 0.3, nxt)
        chars = len(" ".join(w["text"] for w in g))
        size = int(max(60, min(100, 900 / max(1, chars * 0.8))))
        spans = "".join(
            f'<span class="cw{" em" if norm(w["text"]) in emph else ""}" id="cw{gi}_{k}">{esc(w["text"].upper())}</span> '
            for k, w in enumerate(g))
        body.append(f'    <div class="cg" id="cg{gi}" style="font-size:{size}px">{spans.strip()}</div>')
        js.append(f'    tl.fromTo("#cg{gi}", {{ opacity: 0, scale: 0.86, y: 18 }}, '
                  f'{{ opacity: 1, scale: 1, y: 0, duration: 0.14, ease: "back.out(2)" }}, {start:.3f});')
        for k, w in enumerate(g):
            js.append(f'    tl.fromTo("#cw{gi}_{k}", {{ color: "#FFFFFF" }}, {{ color: "{COLORS["yellow"]}", duration: 0.05 }}, {w["start"]:.3f});')
            js.append(f'    tl.to("#cw{gi}_{k}", {{ color: "#FFFFFF", duration: 0.08 }}, {max(w["end"], w["start"] + 0.1):.3f});')
            pop = 1.2 if norm(w["text"]) in emph else 1.12  # active word pops; emphasis words hit harder
            js.append(f'    tl.fromTo("#cw{gi}_{k}", {{ scale: {pop}, rotation: {(-3 if k % 2 else 3) if pop > 1.2 else 0} }}, '
                      f'{{ scale: 1, rotation: 0, duration: 0.18, ease: "back.out(2.2)", immediateRender: false }}, {w["start"]:.3f});')
        js.append(f'    tl.to("#cg{gi}", {{ opacity: 0, duration: 0.08, ease: "power2.in" }}, {end - 0.08:.3f});')
        js.append(f'    tl.set("#cg{gi}", {{ opacity: 0, visibility: "hidden" }}, {end:.3f});')
    css = """
    #root .cg { position:absolute; left:60px; width:900px; top:1110px; height:220px; display:flex; align-items:center; justify-content:center;
      flex-wrap:wrap; column-gap:.25em; text-align:center; opacity:0;
      font-family:'Montserrat',sans-serif; font-weight:900; line-height:1.02; letter-spacing:-.01em;
      -webkit-text-stroke:10px #0B0614; paint-order:stroke fill; text-shadow:0 8px 24px rgba(0,0,0,.6); }
    #root .cw { display:inline-block; color:#FFFFFF; }
    #root .cw.em { color:#FF2E88 !important; }"""
    return scene("captions", total, "\n".join(body), css, "\n".join(js))


def build_chrome(tag, handle, total):
    body = f"""    <div id="ch-pill"><span class="dot"></span>{esc(tag)}</div>
    <div id="ch-bar"><div id="ch-fill"></div></div>
    <div id="ch-handle">{esc(handle)}</div>"""
    css = """
    #ch-pill { position:absolute; left:60px; top:226px; font-family:'Inter',sans-serif; font-weight:900; font-size:34px; letter-spacing:.06em;
      background:rgba(11,6,20,.72); padding:12px 22px 10px; border-radius:999px; border:2px solid rgba(255,255,255,.18); display:flex; align-items:center; gap:12px; }
    #ch-pill .dot { width:16px; height:16px; border-radius:50%; background:#FF2E88; box-shadow:0 0 14px #FF2E88; }
    #ch-bar { position:absolute; left:60px; right:60px; top:206px; height:6px; border-radius:3px; background:rgba(255,255,255,.18); overflow:hidden; }
    #ch-fill { width:100%; height:100%; background:linear-gradient(90deg,#19E3D1,#FF2E88); transform-origin:0 50%; }
    #ch-handle { position:absolute; right:60px; top:234px; font-family:'Inter',sans-serif; font-weight:700; font-size:30px; opacity:.75; }"""
    js = (f'    tl.fromTo("#ch-fill", {{ scaleX: 0 }}, {{ scaleX: 1, duration: {total:.3f}, ease: "none" }}, 0);\n'
          f'    tl.fromTo("#ch-pill", {{ opacity: 0, y: -20 }}, {{ opacity: 1, y: 0, duration: 0.35, ease: "expo.out" }}, 0.1);')
    return scene("chrome", total, body, css, js)


# ---------------------------------------------------------------- vfx (all seek-safe: explicit fromTo/set, closed-form noise)
BEAT_TRANSITIONS = ["zoom", "glitch", "whip", "leak"]  # cycled at beat seams unless beat["tr"] is set
INTRA_TRANSITIONS = ["cut", "whip"]                    # between shots of one beat (no sfx: research says no whoosh on every cut)
TR_SFX = {"zoom": "whoosh", "whip": "whoosh-short", "leak": "whoosh", "glitch": "glitch-1"}
GLITCH_SFX = ["glitch-1", "glitch-3"]
RISER_PEAK = 3.47  # riser.mp3 peaks at 3.47 s (npx hyperframes audio), not at its end


def rnd(*k):
    x = math.sin(sum(v * m for v, m in zip(k, (12.9898, 78.233, 37.719, 4.581)))) * 43758.5453
    return x - math.floor(x)


def shake_js(sel, t, dur=0.42, amp=26, rot=1.0, seed=1):
    out, n = [], max(2, int(round(dur * FPS)))
    for i in range(n):
        k = (1 - i / n) ** 2
        out.append(f'    tl.set("{sel}", {{ x: {amp * k * math.sin(i * 2.9 + seed * 1.7):.1f}, '
                   f'y: {0.7 * amp * k * math.sin(i * 3.7 + seed * 0.9 + 1.3):.1f}, '
                   f'rotation: {rot * k * math.sin(i * 2.3 + seed):.2f} }}, {t + i / FPS:.3f});')
    out.append(f'    tl.set("{sel}", {{ x: 0, y: 0, rotation: 0 }}, {t + n / FPS:.3f});')
    return out


def transition_js(kind, T, k):
    """Camera move on #whip (x, scale) + overlays, centred on the cut at T. Returns (js lines, sfx cues)."""
    js, sfx = [], []
    if kind == "zoom":
        js += [f'    tl.fromTo("#whip", {{ scale: 1 }}, {{ scale: 1.38, duration: 0.15, ease: "power3.in", immediateRender: false }}, {T - 0.15:.3f});',
               f'    tl.fromTo("#whip", {{ scale: 1.38 }}, {{ scale: 1, duration: 0.34, ease: "expo.out", immediateRender: false }}, {T:.3f});',
               f'    tl.fromTo("#flash", {{ opacity: 0.7, backgroundColor: "#FFFFFF" }}, {{ opacity: 0, backgroundColor: "#FFFFFF", duration: 0.2, ease: "power2.out", immediateRender: false }}, {T:.3f});']
        sfx.append(("whoosh", T - 0.16))
    elif kind == "whip":
        d = 1 if k % 2 == 0 else -1
        js += [f'    tl.fromTo("#whip", {{ x: 0, scale: 1 }}, {{ x: {-d * 130}, scale: 1.25, duration: 0.12, ease: "power3.in", immediateRender: false }}, {T - 0.12:.3f});',
               f'    tl.fromTo("#whip", {{ x: {d * 130}, scale: 1.25 }}, {{ x: 0, scale: 1, duration: 0.24, ease: "expo.out", immediateRender: false }}, {T:.3f});']
        sfx.append(("whoosh-short", T - 0.12))
    elif kind == "glitch":
        for f in range(-3, 5):
            t = T + f / FPS
            js.append(f'    tl.set("#whip", {{ x: {(rnd(f, k, 1) - 0.5) * 70:.1f}, scale: {1.03 + 0.05 * rnd(f, k, 2):.3f} }}, {t:.3f});')
            for j in range(7):
                on = rnd(j, f, k, 3) > 0.45
                js.append(f'    tl.set("#gb{j}", {{ y: {rnd(j, f, k, 4) * 1800:.0f}, x: {(rnd(j, f, k, 5) - 0.5) * 220:.0f}, '
                          f'opacity: {0.6 if on else 0} }}, {t:.3f});')
        js.append(f'    tl.set("#whip", {{ x: 0, scale: 1 }}, {T + 5 / FPS:.3f});')
        js.append(f'    tl.set(".gb", {{ opacity: 0 }}, {T + 5 / FPS:.3f});')
        js.append(f'    tl.fromTo("#flash", {{ opacity: 0.4, backgroundColor: "#19E3D1" }}, {{ opacity: 0, backgroundColor: "#19E3D1", duration: 0.16, ease: "power2.out", immediateRender: false }}, {T:.3f});')
        sfx.append((GLITCH_SFX[k % 2], T - 0.1))
    elif kind == "leak":
        js += [f'    tl.fromTo("#leak", {{ xPercent: -70, opacity: 0 }}, {{ xPercent: 40, opacity: 0.95, duration: 0.3, ease: "power2.in", immediateRender: false }}, {T - 0.2:.3f});',
               f'    tl.fromTo("#leak", {{ xPercent: 40, opacity: 0.95 }}, {{ xPercent: 110, opacity: 0, duration: 0.5, ease: "power2.out", immediateRender: false }}, {T + 0.1:.3f});',
               f'    tl.fromTo("#whip", {{ scale: 1.14 }}, {{ scale: 1, duration: 0.4, ease: "expo.out", immediateRender: false }}, {T:.3f});']
        sfx.append(("whoosh", T - 0.18))
    elif kind == "cut":  # hard cut that lands slightly large and settles
        js.append(f'    tl.fromTo("#whip", {{ scale: 1.08 }}, {{ scale: 1, duration: 0.28, ease: "expo.out", immediateRender: false }}, {T:.3f});')
    return js, sfx


def duck_lane(words, total, gain, duck, start=0.0):
    """Music volume lane: ducked under speech, back up in gaps >= 0.35 s, 1 s fade at the end."""
    segs = []
    for w in words:
        if segs and w["start"] - segs[-1][1] < 0.35:
            segs[-1][1] = w["end"]
        else:
            segs.append([w["start"], w["end"]])
    pts = [(0.0, gain)]
    for a, b in segs:
        pts += [(max(0.0, a - 0.12), gain if a > 0.15 else duck), (a, duck), (b, duck), (b + 0.25, gain)]
    pts += [(total - 1.0, gain), (total, 0.0)]
    clean, last = [], -1.0
    for t, v in sorted(pts):
        t = round(max(0.0, t - start), 3)
        if t > last:
            clean.append({"t": t, "v": round(v, 3)})
            last = t
    return json.dumps({"version": 1, "lanes": [{"target": "volume", "points": clean}]}, separators=(",", ":"))


# ---------------------------------------------------------------- main
def main(short_dir):
    sd = Path(short_dir).resolve()
    spec = json.loads((sd / "short.json").read_text())
    words = load_words(sd / spec["words"])
    total = round(words[-1]["end"] + spec.get("tail", 1.2), 3)
    shots = load_catalog()

    beats = spec["beats"]
    t = 0.0
    for b in beats:
        b["t0"] = 0.0 if not b.get("anchor") else round(resolve_anchor(words, b["anchor"], t) - 0.08, 3)
        t = b["t0"]
    for i, b in enumerate(beats):
        b["t1"] = beats[i + 1]["t0"] if i + 1 < len(beats) else total

    (sd / "compositions").mkdir(exist_ok=True)
    for old in (sd / "assets/clips").glob("*.mp4") if (sd / "assets/clips").exists() else []:
        old.unlink()
    videos, hosts, sfx_cues, kb_js, fx_js = [], [], [], [], []
    cuts = []  # clip start times (> 0)
    settle = []  # times where every card has landed: safe-zone check samples
    clip_i = 0
    for bi, b in enumerate(beats):
        bdur = b["t1"] - b["t0"]
        weights = [s.get("w", 1.0) for s in b["shots"]]
        acc = b["t0"]
        if not b["shots"] and bi > 0:  # motion-design beat: flash into it, the card brings its own ground
            fx_js.append(f'    tl.fromTo("#flash", {{ opacity: 0.6, backgroundColor: "#FFFFFF" }}, {{ opacity: 0, backgroundColor: "#FFFFFF", duration: 0.18, ease: "power2.out", immediateRender: false }}, {b["t0"]:.3f});')
            sfx_cues.append(("whoosh-short", b["t0"] - 0.1))
        for si, (s, wgt) in enumerate(zip(b["shots"], weights)):
            d = round(bdur * wgt / sum(weights), 3)
            s = {**s, "look": spec.get("look", "vice")}
            src = cut_clip(sd, shots, s, d, clip_i)
            videos.append(f'        <video id="v{clip_i:02d}" class="clip" src="{src}" data-start="{acc:.3f}" data-duration="{d:.3f}" '
                          f'data-track-index="0" muted playsinline></video>')
            # Ken Burns on #stage: alternate push-in / drift
            s0, s1 = (1.0, 1.07) if clip_i % 2 == 0 else (1.08, 1.02)
            kb_js.append(f'    tl.fromTo("#stage", {{ scale: {s0} }}, {{ scale: {s1}, duration: {d:.3f}, ease: "none", immediateRender: false }}, {acc:.3f});')
            if acc > 0:
                cuts.append(acc)
                kind = (b.get("tr") or BEAT_TRANSITIONS[(bi - 1) % len(BEAT_TRANSITIONS)]) if si == 0 \
                    else s.get("tr", INTRA_TRANSITIONS[clip_i % len(INTRA_TRANSITIONS)])
                js, sfx = transition_js(kind, acc, clip_i)
                fx_js += js
                if si == 0:
                    sfx_cues += sfx
            acc = round(acc + d, 3)
            clip_i += 1
        # card
        c = b.get("card")
        if c:
            cid = f"card-{b['id']}"
            rel = lambda txt, b=b: resolve_anchor(words, txt, b["t0"]) - b["t0"]
            body, css, js, sfx = CARDS[c["type"]](cid, c, bdur, rel)
            settle.append(round(b["t0"] + min(bdur - 0.35, max(1.0, 0.75 * bdur)), 2))
            (sd / "compositions" / f"{cid}.html").write_text(scene(cid, bdur, body, css, js))
            hosts.append(f'      <div id="{cid}" data-composition-id="{cid}" data-composition-src="compositions/{cid}.html" '
                         f'data-start="{b["t0"]:.3f}" data-duration="{bdur:.3f}" data-track-index="2" data-track-kind="graphics" '
                         f'data-width="{W}" data-height="{H}" style="z-index:{10 + bi}"></div>')
            # the seam already has its own whoosh: keep only impacts and later cues from the card
            sfx_cues += [(name, b["t0"] + at) for name, at in sfx if bi == 0 or at > 0.12 or name.startswith("impact")]
        # impacts: camera shake (hook, payoff, cta, or beat["shake"])
        if b.get("shake", c and c["type"] in ("hook", "cta") or b.get("payoff")):
            fx_js += shake_js("#cam", b["t0"] + (0.02 if bi else 1 / FPS), seed=bi + 1)
        if b.get("payoff") and b["t0"] > 1.6:  # riser that peaks on the reveal, once per film
            sfx_cues.append(("riser", b["t0"] - 1.5))

    # punch-ins on spoken words: #zoom jumps in and holds until the next cut
    for ph in spec.get("punch", []):
        tp = resolve_anchor(words, ph, 0.0)
        nxt = next((c for c in cuts if c > tp + 0.05), total)
        if nxt - tp < 0.35:
            print(f"  ! punch {ph!r} trop près d'un cut, ignoré")
            continue
        fx_js.append(f'    tl.fromTo("#zoom", {{ scale: 1.2 }}, {{ scale: 1.13, duration: 0.22, ease: "expo.out", immediateRender: false }}, {tp:.3f});')
        fx_js.append(f'    tl.set("#zoom", {{ scale: 1 }}, {nxt:.3f});')
        fx_js += shake_js("#cam", tp, dur=0.2, amp=12, rot=0.5, seed=int(tp * 10))

    (sd / "compositions/captions.html").write_text(build_captions(words, total, spec.get("emphasis", [])))
    (sd / "compositions/chrome.html").write_text(build_chrome(spec.get("tag", "GTA 6 · ACTU"), spec.get("handle", ""), total))

    # audio: voice, sfx (peak one frame after the picture), riser trimmed to its last 1.5 s, ducked music
    (sd / "assets/sfx").mkdir(parents=True, exist_ok=True)
    audio = [f'      <audio id="vo" class="clip" src="{spec["voice"]}" data-start="0" data-track-index="5" data-volume="1"></audio>']
    manifest = json.loads((SFX_LIB / "manifest.json").read_text())
    vols = {"impact": 0.5, "riser": 0.35, "glitch": 0.22, "click": 0.25}
    for i, (name, at) in enumerate(sorted(sfx_cues, key=lambda x: x[1])):
        if at >= total - 0.2 or at < 0:
            continue
        shutil.copy(SFX_LIB / f"{name}.mp3", sd / "assets/sfx" / f"{name}.mp3")
        vol = next((v for k, v in vols.items() if name.startswith(k)), 0.3)
        full = manifest[name]["duration"]
        mstart, dur = (RISER_PEAK - 1.5, 1.75) if name == "riser" else (0.0, min(0.6 if name.startswith("glitch") else full, total - at - 0.05))
        audio.append(f'      <audio id="sfx{i:02d}" class="clip" src="assets/sfx/{name}.mp3" data-start="{at + 0.033:.3f}" '
                     f'data-duration="{dur:.3f}"{f" data-media-start={chr(34)}{mstart:.3f}{chr(34)}" if mstart else ""} '
                     f'data-track-index="{6 + i % 3}" data-volume="{vol}"></audio>')
    m = spec.get("music")
    if m:
        m = {"src": m} if isinstance(m, str) else m
        lane = duck_lane(words, total, m.get("gain", 0.3), m.get("duck", 0.12))
        audio.append(f'      <audio id="bgm" class="clip" src="{m["src"]}" data-start="0" data-duration="{total:.3f}" '
                     f'data-media-start="{m.get("from", 0):.3f}" data-track-index="9" data-volume="1" '
                     f"data-automation='{lane}'></audio>")

    bars = "\n".join(f'        <div class="gb" id="gb{j}" style="height:{int(6 + 54 * rnd(j, 9))}px;'
                     f'background:{"#FF2E88" if j % 2 else "#19E3D1"}"></div>' for j in range(7))
    index = f"""<!doctype html>
<html lang="fr">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={W}, height={H}" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js"></script>
    <style>
      * {{ margin:0; padding:0; box-sizing:border-box; }}
      html, body {{ width:{W}px; height:{H}px; overflow:hidden; background:#0B0614; }}
      #root {{ position:relative; width:100%; height:100%; overflow:hidden; }}
      #bg {{ position:absolute; inset:0; background:#0B0614; }}
      #cam, #whip, #zoom, #stage {{ position:absolute; inset:0; }}
      #whip, #zoom {{ transform-origin:50% 50%; }}
      #stage {{ transform-origin:50% 45%; }}
      #stage video {{ position:absolute; left:0; top:0; width:{W}px; height:{H}px; object-fit:cover; }}
      #scrim-top {{ position:absolute; left:0; right:0; top:0; height:900px; z-index:5;
        background:linear-gradient(180deg, rgba(11,6,20,.78) 0%, rgba(11,6,20,.35) 45%, rgba(11,6,20,0) 100%); }}
      #scrim-bot {{ position:absolute; left:0; right:0; bottom:0; height:900px; z-index:5;
        background:linear-gradient(0deg, rgba(11,6,20,.8) 0%, rgba(11,6,20,.3) 55%, rgba(11,6,20,0) 100%); }}
      #glitch {{ position:absolute; inset:0; z-index:6; pointer-events:none; }}
      #glitch .gb {{ position:absolute; left:-120px; right:-120px; top:0; opacity:0; mix-blend-mode:screen; }}
      #leak {{ position:absolute; top:-200px; left:-300px; width:1700px; height:2400px; z-index:7; opacity:0; mix-blend-mode:screen;
        background:radial-gradient(closest-side, rgba(255,214,120,.95), rgba(255,138,61,.75) 40%, rgba(255,46,136,.45) 70%, rgba(255,46,136,0)); }}
      #flash {{ position:absolute; inset:0; z-index:40; background:#FF2E88; mix-blend-mode:screen; opacity:0; }}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{total:.3f}" data-width="{W}" data-height="{H}" data-motion-blur="{spec.get('motion_blur', 'on')}">
      <div id="bg"></div>
      <div id="cam"><div id="whip"><div id="zoom"><div id="stage">
{chr(10).join(videos)}
      </div></div></div></div>
      <div id="scrim-top"></div>
      <div id="scrim-bot"></div>
      <div id="glitch">
{bars}
      </div>
      <div id="leak"></div>
{chr(10).join(hosts)}
      <div id="captions" data-composition-id="captions" data-composition-src="compositions/captions.html" data-start="0" data-duration="{total:.3f}" data-track-index="3" data-track-kind="captions" data-width="{W}" data-height="{H}" style="z-index:30"></div>
      <div id="chrome" data-composition-id="chrome" data-composition-src="compositions/chrome.html" data-start="0" data-duration="{total:.3f}" data-track-index="4" data-track-kind="graphics" data-width="{W}" data-height="{H}" style="z-index:35"></div>
      <div id="flash"></div>
{chr(10).join(audio)}
    </div>
    <script>
      const tl = gsap.timeline({{ paused: true }});
      tl.set("#cam", {{ x: 0, y: 0, rotation: 0, scale: 1.06 }}, 0);  // headroom so shakes never show an edge
      tl.set("#whip", {{ x: 0, scale: 1 }}, 0);
      tl.set("#zoom", {{ scale: 1 }}, 0);
      tl.set(".gb", {{ opacity: 0 }}, 0);
{chr(10).join(kb_js)}
{chr(10).join(fx_js)}
      window.__timelines["main"] = tl;
    </script>
  </body>
</html>
"""
    (sd / "index.html").write_text(index)
    print(f"built {sd.name}: {total:.2f}s, {clip_i} clips, {len(hosts)} cards, {len(audio) - 1} audio, {len(cuts)} cuts")
    print("check: npx hyperframes check --json --at " + ",".join(f"{t:g}" for t in settle))


if __name__ == "__main__":
    main(sys.argv[1])
