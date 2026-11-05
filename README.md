# GTA6Short

Pipeline de shorts verticaux (1080×1920, 30 s–1 min) d'actu **GTA 6 en français** : sujet sourcé → script → voix IA → montage motion design dynamique → MP4 prêt pour TikTok, Reels et YouTube Shorts.

Moteur : [HyperFrames](https://hyperframes.heygen.com) (HTML + GSAP → MP4), orchestré par Claude Code.

## Comment ça marche
1. **Sujets** : `news/<NNN-slug>.json` (modèle `news/_TEMPLATE.json`) — faits chiffrés + sources. Statuts `todo → script → review → published`.
2. **Production** : skill Claude Code `/gta6-short` (`.claude/skills/gta6-short/SKILL.md`) — script sourcé, voix ElevenLabs, choix des plans dans `catalog/shots.json`, `short.json`.
3. **Mécanique** : `scripts/pipeline.py` (`status`, `new`, `tts`, `build`, `render`, `set`).
4. **Générateur** : `scripts/build_short.py` — `short.json` → composition HyperFrames avec transitions (zoom, glitch, whip, light leak), punch-ins, camera shake, étalonnage + grain, sous-titres mot par mot, cartes animées (horloge, jauge de stockage, frise, tampon…), musique avec ducking, et **zone sûre multi-plateformes** vérifiée automatiquement.

## Prérequis
- Node + `npx hyperframes` (0.9.x), ffmpeg, Python 3
- `.env` : `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL` (jamais commité)
- Footage : trailers officiels Rockstar téléchargés en local (`footage/`, non versionné) puis `scripts/index_footage.py`
- Musique : `npx hyperframes auth login` puis `node scripts/find_music.mjs "<ambiance>"`

## Droits
Ce dépôt ne contient que du code et des métadonnées. Le footage (© Rockstar Games), les musiques et les effets sonores ne sont pas redistribués.
GTA 6 est une marque de Rockstar Games / Take-Two Interactive ; projet de fans non affilié.
