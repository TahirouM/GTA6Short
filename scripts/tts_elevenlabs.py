#!/usr/bin/env python3
"""ElevenLabs TTS with word timestamps (stdlib only).

Usage:
  python3 -I scripts/tts_elevenlabs.py SCRIPT.txt OUT_DIR [--voice ID] [--model ID]
  python3 -I scripts/tts_elevenlabs.py --list-voices

Reads ELEVENLABS_API_KEY (and optional ELEVENLABS_VOICE_ID, ELEVENLABS_MODEL) from env or ./.env.
Writes OUT_DIR/voice.mp3 and OUT_DIR/words.json:
  [{"id": "w0", "text": "Plus", "start": 0.06, "end": 0.27}, ...]
"""
import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.elevenlabs.io/v1"


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def call(path, body=None):
    req = urllib.request.Request(
        API + path, data=json.dumps(body).encode() if body else None,
        headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"], "Content-Type": "application/json"},
        method="POST" if body else "GET")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"ElevenLabs {e.code}: {e.read().decode()[:400]}")


def words_from_alignment(al):
    chars, starts, ends = al["characters"], al["character_start_times_seconds"], al["character_end_times_seconds"]
    words, cur, ws, we = [], "", None, None
    for ch, s, e in zip(chars, starts, ends):
        if ch.isspace():
            if cur:
                words.append((cur, ws, we))
            cur, ws = "", None
            continue
        if ws is None:
            ws = s
        cur += ch
        we = e
    if cur:
        words.append((cur, ws, we))
    return [{"id": f"w{i}", "text": t, "start": round(s, 3), "end": round(e, 3)}
            for i, (t, s, e) in enumerate(words)]


def main():
    load_env()
    if "ELEVENLABS_API_KEY" not in os.environ:
        sys.exit("ELEVENLABS_API_KEY manquant (mets-le dans .env à la racine du projet)")
    ap = argparse.ArgumentParser()
    ap.add_argument("script", nargs="?")
    ap.add_argument("out_dir", nargs="?")
    ap.add_argument("--voice", default=os.environ.get("ELEVENLABS_VOICE_ID"))
    ap.add_argument("--model", default=os.environ.get("ELEVENLABS_MODEL", "eleven_multilingual_v2"))
    ap.add_argument("--stability", type=float, default=0.4)
    ap.add_argument("--style", type=float, default=0.35)
    ap.add_argument("--speed", type=float, default=1.05)
    ap.add_argument("--list-voices", action="store_true")
    a = ap.parse_args()

    if a.list_voices:
        for v in call("/voices")["voices"]:
            lab = v.get("labels", {})
            print(f"{v['voice_id']}  {v['name']:<28} {lab.get('language', ''):<6} {lab.get('gender', ''):<7} {lab.get('accent', '')} {lab.get('description', '')}")
        return
    if not (a.script and a.out_dir and a.voice):
        sys.exit("usage: tts_elevenlabs.py SCRIPT.txt OUT_DIR --voice ID (ou ELEVENLABS_VOICE_ID dans .env)")

    text = Path(a.script).read_text().strip()
    res = call(f"/text-to-speech/{a.voice}/with-timestamps?output_format=mp3_44100_128", {
        "text": text, "model_id": a.model, "language_code": "fr",
        "voice_settings": {"stability": a.stability, "similarity_boost": 0.8, "style": a.style,
                           "use_speaker_boost": True, "speed": a.speed},
    })
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "voice.mp3").write_bytes(base64.b64decode(res["audio_base64"]))
    words = words_from_alignment(res["alignment"])  # alignment on the original text = caption text
    (out / "words.json").write_text(json.dumps(words, ensure_ascii=False, indent=1))
    print(f"voice.mp3 + words.json ({len(words)} mots, fin {words[-1]['end']:.2f}s) -> {out}")


if __name__ == "__main__":
    main()
