---
name: gta6-short
description: Produire un ou plusieurs shorts verticaux (1080x1920, 30 s–1 min) d'actu GTA 6 en français — sujet/news → script sourcé, voix Nicolas Petit (ElevenLabs), plans du catalogue (plan glamour en ouverture), motion design HyperFrames dynamique, zone sûre TikTok/Reels/Shorts, musique HeyGen, captures à valider, rendu MP4. À utiliser dès que l'utilisateur demande un short, un TikTok/Reel/Short GTA 6, passe une news de news/, ou demande de « traiter la file » / produire en masse.
---

# Shorts d'actu GTA 6

Semi-auto : je produis tout, l'utilisateur valide (1) les scripts, (2) les captures/MP4 avant publication.
Lire `/hyperframes` (contrat, `references/types/vertical.md`, `motion.md`, `sound.md`) avant de toucher au HTML.
Mécanique : `scripts/pipeline.py` (status · new · tts · build · render · set). Créatif : moi (script, plans, short.json).

## File de sujets (production en série)
- Un sujet = `news/<NNN-slug>.json` (copier `news/_TEMPLATE.json`) : `title`, `type` (officiel/rumeur/leak), `facts[]`, `sources[]`, `angle?`, `notes?`.
- Statuts : `todo` → `script` (projet créé, script à valider) → `review` (MP4 rendu, à valider) → `published` | `skip`.
- `python3 -I scripts/pipeline.py status` liste la file. Numérotation des shorts continue (`003-…`, `004-…`).
- **Mode série** (« traite la file », « fais les shorts ») : pour TOUS les `todo`, écrire les scripts et les montrer **en un seul message** (un bloc par sujet + plan des beats) → une seule validation → puis TTS, build, check, captures, rendu de chaque short → une seule synthèse finale (tableau : sujet, durée, LUFS, chemin MP4, titre/description/hashtags). Ne pas redemander entre deux shorts sauf blocage.
- Quota ElevenLabs Starter ≈ 38 750 caractères/mois ≈ 50 shorts de ~700 caractères : annoncer le coût du lot avant de lancer les TTS.

## 1. Script (FR, 100–140 mots ≈ 32–50 s — l'utilisateur veut 30 s à 1 min)
- **Sources** : jamais de fait non sourcé ; vérifier sur le Newswire Rockstar en priorité, recouper la presse. Rumeur/leak annoncé comme tel dans la voix ET à l'écran. Pas de leaks 2022.
- Phrase 1 = hook (le chiffre ou le fait le plus fort), compris sans le son. Un fait par beat, 7–10 beats. Dernier beat = CTA-question qui renvoie au hook (boucle).
- Nombres prononcés en lettres (« deux cent douze gigas », « dix-neuf novembre ») ; « GTA 6 », « PS5 », « Xbox » passent tels quels.
- Ton oral, tutoiement, phrases courtes. Varier la structure d'un short à l'autre (politique YouTube « inauthentic content », juillet 2026).

## 2. Projet + voix
```bash
python3 -I scripts/pipeline.py new <NNN-slug> <news_id>     # copie shorts/_template, statut -> script
# écrire shorts/<slug>/assets/audio/script.txt
python3 -I scripts/pipeline.py tts <slug>                    # imprime les timings mot par mot (pour les anchors)
```
Voix : **Nicolas Petit – Convincing and Bright** (`AmMsHJaCw4BtwV3KoUXF`), `eleven_v4`, speed 1.1, stability 0.5, style 0 — défauts dans `.env` (plan Starter : voix de la Library OK en API).

## 3. Plans
- `catalog/shots.json` (`<videoId>#<n>`) + planches `catalog/sheets/<videoId>_<k>.jpg` — LES REGARDER.
- Vidéos : `QdBZY2fkU-0` Trailer 1 · `VQRLujxTm3c` Trailer 2 · `tJbzMqJGH4k` Extended Look (27 min, la plus riche).
- **1er extrait = plan féminin glamour** (demande utilisateur) : plans taggés `glamour`, classés par `glam_rank` avec `focus_x` réglé (n°1 `QdBZY2fkU-0#017`, n°2 `#028`, n°3 `#008`, n°4 `#010`, `VQRLujxTm3c#027`, `tJbzMqJGH4k#038`…). Tourner entre eux d'un short à l'autre. Carte hook en `"pos": "low"`. Les reprendre aussi sur 1–2 autres beats (ex. bonus, lifestyle).
- Exclure : cartons ESRB/noirs, logos et « Rockstar Games presents », plans avec UI de réseaux sociaux fictifs.
- Plans de 1–2,5 s ; `focus` 0–1 = position horizontale du sujet ; `fit: "frame"` = 16:9 sur fond flouté ; plan trop court ralenti auto (≥0,5x).
- Nouveau footage : `yt-dlp` ≤1080p dans `footage/official|gameplay/` puis `.venv/bin/python -I scripts/index_footage.py` (cookies Dia si âge : `uv run --with yt-dlp python -I scripts/dia_cookies.py <fichier>`, dans le scratchpad, supprimé après).

## 4. Musique (une par short, varier)
```bash
node scripts/find_music.mjs "retro 80s synthwave neon night drive" assets/music   # catalogue HeyGen (auth login fait)
npx hyperframes audio assets/music/<id>.mp3 --json                                 # moments.peak
cp assets/music/<id>.mp3 shorts/<slug>/assets/audio/bgm.mp3
```
`"music": {"src": "assets/audio/bgm.mp3", "from": <s>, "gain": 0.3, "duck": 0.11}` — `from` cale le pic du morceau sur le beat `payoff` si possible. Ducking auto sous la voix. Noter l'id du morceau dans la news (`"music"`).
Bibliothèque déjà téléchargée : `assets/music/` (47226d7a = 80s Miami, utilisée par 002 ; 421a4ab1, 600a349c, 98bd24a4, …).

## 5. short.json → build
Schéma complet : docstring de `scripts/build_short.py`. Exemple de référence : `shorts/002-prechargement/short.json`.
- `anchor` = 2–3 mots de la voix (évite les faux positifs), `emphasis` = mots en rose, `punch` = 2–4 expressions clés (punch-in + micro-shake).
- Cartes : `hook` · `headline` (+`chips`, `style: "alert"`) · `place` · `names` · `stat` · `clock` (chiffres à rouleaux) · `stamp` (un « non ») · `cta`.
- **Motion design pur** quand ça sert l'info (chiffre, comparaison, dates) : beat `"shots": []` + `storage` {label, device, used, total, total_label, sub} ou `timeline` {label, items:[{date, text, at | lit}]}. 1–2 par short, pas plus.
- Transitions de couture `tr` : zoom · glitch · whip · leak · cut (varier) ; `payoff: true` sur LA révélation (riser + shake) ; `shake: true` sur un impact.
```bash
python3 -I scripts/pipeline.py build <slug>   # build + check zone sûre + captures (0, puis 1 par beat posé)
```
- **Zone sûre TikTok/Reels/Shorts** : cartes dans une boîte fixe x 60–960 / y 310–1090, sous-titres y 1110–1330, chrome y≈206–290 ; tailles auto-ajustées. Exigé : **0 `text_box_overflow`** (le build échoue sinon). Le check ne voit pas les **chevauchements** : les chercher sur les captures (ex. dates/libellés), ainsi que visages masqués, texte illisible sur fond clair, bandes noires.
- Faux positifs connus (filtrés par pipeline.py) : `text_occluded` sur `#card-*-d*` (rouleaux), contraste des textes à contour, `container/canvas_overflow` des fonds MD et barres glitch.

## 6. Validation puis rendu
Montrer les planches de captures. Après accord :
```bash
python3 -I scripts/pipeline.py render <slug>   # MP4 delivery + LUFS (cible -16..-14) ; news -> review
```
Livrer : chemin MP4, durée, LUFS, titre / description (avec sources) / hashtags (#GTA6 #GTAVI #Rockstar #RockstarGames #PS5 #XboxSeriesX #ViceCity), crédits (SFX Pixabay sans attribution requise ; musique catalogue HeyGen). Je ne publie jamais moi-même ; après publication par l'utilisateur : `pipeline.py set <news_id> published`.

## Identité visuelle
Palette Vice City : rose `#FF2E88`, orange `#FF8A3D`, teal `#19E3D1`, nuit `#0B0614`, jaune `#FFE14D`. Titres Archivo Black, sous-titres Montserrat 900 majuscules (mot actif jaune qui « pop »). Pastille « GTA 6 · ACTU » + handle + barre de progression. Look « vice » (étalonnage + grain + vignette) intégré aux clips. Son du footage coupé (Content ID) ; voix + SFX Pixabay + musique HeyGen.
