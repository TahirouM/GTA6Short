// Search HeyGen's music catalog and download candidates (needs `npx hyperframes auth login`).
// Usage: node scripts/find_music.mjs "<mood query>" [outDir=assets/music] [limit=6]
// Prints id, score, duration, description; downloads tracks >= 30 s as <outDir>/<id8>.mp3.
// Then: pick one, measure it (`npx hyperframes audio <file> --json` -> moments.peak), copy it to
// shorts/<slug>/assets/audio/bgm.mp3 and set "music": {"src", "from"} in short.json.
import { existsSync } from "node:fs";
const { searchSounds, heygenAuthHeaders, downloadTo } = await import(
  `${process.env.HOME}/.claude/skills/media-use/audio/scripts/lib/heygen.mjs`);

const [query, outDir = "assets/music", limit = "6"] = process.argv.slice(2);
if (!query) { console.error("usage: node scripts/find_music.mjs \"<mood>\" [outDir] [limit]"); process.exit(1); }
const results = await searchSounds(query, "music", heygenAuthHeaders(), { limit: Number(limit), minScore: 0.4 });
for (const x of results) {
  const id = x.id.slice(0, 8);
  const path = `${outDir}/${id}.mp3`;
  const keep = (x.duration ?? 0) >= 30;
  if (keep && !existsSync(path)) await downloadTo(x.audio_url, path);
  console.log(`${keep ? "DL " : "   "}${id}  ${x.score?.toFixed(2)}  ${String(x.duration).padStart(3)}s  ${x.description ?? x.name}`);
}
