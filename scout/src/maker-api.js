// AI helpers for the Short maker (GitHub Actions), all on your free Workers AI:
//   writeScript  - Qwen writes the hook, voiceover, title and hashtags
//   speak        - backup voice (Deepgram Aura) if VoiceStudio is not available
//   transcribe   - Whisper gives word timings for the captions
import { extractText, runQwen } from "./rank.js";

const WRITER =
  "You write for 'Viceverified', a GTA 6 YouTube Shorts / TikTok channel. " +
  "Use ONLY facts in the given text - never invent numbers, dates, names or quotes. " +
  "Energetic, simple English, short sentences, no emojis in the voiceover. Reply with JSON only.";

export function buildWritePrompt(req) {
  if (req.kind === "clip") {
    return (
      `Stream clip from ${req.author || "a streamer"} playing GTA 6.\n` +
      `Clip title: ${req.title}\nViews: ${req.metric || "?"}\n` +
      (req.transcript ? `What is said in the clip: ${String(req.transcript).slice(0, 1200)}\n` : "") +
      `\nReturn JSON exactly like:\n` +
      `{"hook": "on-screen hook, max 8 words", "title": "max 70 chars", ` +
      `"caption": "1-2 sentence caption that credits the streamer", "hashtags": ["#gta6", "... 8 total"], ` +
      `"safe": true}\n` +
      `Set "safe" to false if the clip is about nudity, sex, strip clubs, slurs or real-world violence.\n/no_think`
    );
  }
  return (
    `Headline: ${req.title}\nSource: ${req.author || "news site"}\n` +
    (req.angle ? `Angle idea: ${req.angle}\n` : "") +
    `Article text: ${String(req.facts || req.title).slice(0, 3500)}\n\n` +
    `Return JSON exactly like:\n` +
    `{"hook": "on-screen hook, max 7 words", ` +
    `"voiceover": "80-110 words. First sentence is the hook. Say the source name once. End with: Follow for daily GTA 6 news.", ` +
    `"title": "max 70 chars", "caption": "1-2 sentences", "hashtags": ["#gta6", "... 8 total"], "safe": true}\n` +
    `Set "safe" to false if the story is about nudity, sex, slurs or real-world violence.\n/no_think`
  );
}

export function parseObject(text) {
  const clean = String(text).replace(/<think>[\s\S]*?<\/think>/g, "");
  const m = clean.match(/\{[\s\S]*\}/);
  if (!m) throw new Error("Qwen gave no JSON");
  return JSON.parse(m[0]);
}

export async function writeScript(env, req) {
  const out = await runQwen(env, [
    { role: "system", content: WRITER },
    { role: "user", content: buildWritePrompt(req) },
  ]);
  const s = parseObject(extractText(out));
  return {
    hook: String(s.hook || req.title).slice(0, 80),
    voiceover: String(s.voiceover || "").slice(0, 1200),
    title: String(s.title || req.title).slice(0, 100),
    caption: String(s.caption || "").slice(0, 500),
    hashtags: Array.isArray(s.hashtags) ? s.hashtags.map(String).slice(0, 12) : [],
    safe: s.safe !== false,
  };
}

export async function speak(env, text, speaker) {
  const model = env.TTS_MODEL || "@cf/deepgram/aura-1";
  const res = await env.AI.run(
    model,
    { text: String(text).slice(0, 1900), speaker: speaker || env.TTS_SPEAKER || "orion", encoding: "mp3" },
    { returnRawResponse: true },
  );
  return new Response(res.body, { headers: { "Content-Type": "audio/mpeg", "Cache-Control": "no-store" } });
}

function toBase64(bytes) {
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

/** Normalises the different Whisper outputs to [{word, start, end}]. */
export function wordsFrom(out) {
  if (Array.isArray(out?.words) && out.words.length) {
    return out.words.map((w) => ({ word: String(w.word).trim(), start: +w.start, end: +w.end }));
  }
  const words = [];
  for (const seg of out?.segments || []) {
    for (const w of seg.words || []) words.push({ word: String(w.word).trim(), start: +w.start, end: +w.end });
  }
  return words.filter((w) => w.word);
}

export async function transcribe(env, audioBytes) {
  const model = env.STT_MODEL || "@cf/openai/whisper-large-v3-turbo";
  const input = model.includes("large-v3-turbo")
    ? { audio: toBase64(new Uint8Array(audioBytes)), language: "en" }
    : { audio: [...new Uint8Array(audioBytes)] };
  const out = await env.AI.run(model, input);
  return { text: out?.text || "", words: wordsFrom(out) };
}
