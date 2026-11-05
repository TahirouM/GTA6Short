# GTA6Short

Pipeline de shorts verticaux (1080x1920) d'actu GTA 6, en français.

- Partie 1 : sujets → `news/<NNN-slug>.json` (modèle `news/_TEMPLATE.json`, statuts todo → script → review → published)
- Partie 2 : production des shorts (un ou en série) → skill projet **`/gta6-short`** + `scripts/pipeline.py`

## Stack
- Motion design / rendu : **HyperFrames** 0.9.10 (HTML + GSAP → MP4), skills globaux `/hyperframes`, `/hyperframes-cli`, `/hyperframes-registry`, `/media-use`
- Générateur : `scripts/build_short.py` (short.json → index.html + compositions/, VFX, zone sûre) ; orchestration `scripts/pipeline.py`
- Musique : catalogue HeyGen via `scripts/find_music.mjs` → `assets/music/`
- Voix : ElevenLabs Starter, Nicolas Petit + `eleven_v4` (`scripts/tts_elevenlabs.py`, clé dans `.env`, jamais commitée)
- Footage : `yt-dlp` ≤1080p → `footage/official/`, `footage/gameplay/` ; index `scripts/index_footage.py` (`.venv`, Pillow) → `footage/proxy/`, `catalog/`
- `shorts/_template/` = projet HyperFrames vierge à copier ; `shorts/<NNN-slug>/` = un short

## Règles
- Sources vidéo : officiel Rockstar + gameplay post-sortie (19 nov 2026). Pas de leaks 2022.
- Toujours passer par les proxys (H.264 GOP court), jamais les sources AV1.
- Disque limité (~25 Go libres) : 1080p max, pas de 4K.
- Semi-auto : scripts puis captures + MP4 validés par l'utilisateur avant publication.
- Format : 30 s–1 min, 1er plan glamour, motion design pur quand ça sert l'info, textes dans la zone sûre TikTok/Reels/Shorts.
