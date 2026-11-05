#!/usr/bin/env python3
"""Align the exact script text onto a whisper transcript's word timings.

Used for local/draft voices (Kokoro). ElevenLabs gives words.json directly.
Usage: python3 -I scripts/align_words.py script.txt transcript.json words.json
"""
import difflib
import json
import re
import sys
import unicodedata


def norm(w):
    w = unicodedata.normalize("NFKD", w.lower())
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in w if not unicodedata.combining(c)))


def main(script, transcript, out):
    words = open(script).read().split()
    t = json.load(open(transcript))
    t = t if isinstance(t, list) else t.get("words", [])
    t = [x for x in t if norm(x["text"])]
    a, b = [norm(w) for w in words], [norm(x["text"]) for x in t]
    times = [None] * len(words)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                times[i1 + k] = (t[j1 + k]["start"], t[j1 + k]["end"])
        elif tag == "replace" and j2 > j1:
            # spread the transcript span over the script words by character count
            s0, e0 = t[j1]["start"], t[j2 - 1]["end"]
            lens = [max(1, len(a[i])) for i in range(i1, i2)]
            tot, acc = sum(lens), 0
            for k, i in enumerate(range(i1, i2)):
                st = s0 + (e0 - s0) * acc / tot
                acc += lens[k]
                times[i] = (st, s0 + (e0 - s0) * acc / tot)
    # fill leftover gaps by interpolation between neighbours
    for i, tm in enumerate(times):
        if tm is None:
            prev = next((times[j][1] for j in range(i - 1, -1, -1) if times[j]), 0.0)
            nxt = next((times[j][0] for j in range(i + 1, len(times)) if times[j]), prev + 0.3)
            times[i] = (prev, max(prev + 0.05, nxt))
    res = [{"id": f"w{i}", "text": w, "start": round(s, 3), "end": round(e, 3)}
           for i, (w, (s, e)) in enumerate(zip(words, times))]
    json.dump(res, open(out, "w"), ensure_ascii=False, indent=1)
    print(f"{len(res)} words -> {out}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
