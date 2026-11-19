// Scores each find 0-100: "would this make a good GTA 6 Short today?"
// Free rules give a first score; Qwen re-scores the best ones and writes a Short idea.
import { hoursAgo } from "./util.js";

export const DEFAULT_MODEL = "@cf/qwen/qwen3.8-27b";

const HOT_WORDS = [
  ["leak", 18], ["trailer", 16], ["release", 12], ["launch", 12], ["delay", 16], ["price", 10],
  ["map", 10], ["rockstar", 8], ["update", 8], ["patch", 8], ["online", 8], ["record", 10],
  ["sales", 8], ["glitch", 10], ["secret", 10], ["easter egg", 12], ["lucia", 6], ["jason", 6],
  ["vice city", 6], ["pc", 8], ["dlc", 8], ["first look", 10], ["official", 8], ["confirmed", 10],
  ["hidden", 8], ["world record", 12], ["funny", 6], ["insane", 4],
];

export function ruleScore(item, now = Date.now()) {
  const t = `${item.title} ${item.author || ""}`.toLowerCase();
  let s = 20;
  for (const [w, pts] of HOT_WORDS) if (t.includes(w)) s += pts;
  const age = hoursAgo(item.published_at, now);
  s += age < 6 ? 15 : age < 24 ? 8 : age < 72 ? 0 : -15;
  if (item.metric > 0) s += Math.min(30, Math.round(Math.log10(item.metric + 1) * 7));
  if (item.kind === "clip") s += 5;
  return Math.max(0, Math.min(100, s));
}

const SYSTEM =
  "You are the scout for a GTA 6 YouTube Shorts / TikTok channel. You judge which finds would make " +
  "a viral 30-60 second Short TODAY. Reward genuinely new info, official Rockstar news, leaks, big " +
  "moments from streamers, funny or shocking clips. Punish rumours already old, clickbait, duplicates, " +
  "and non-GTA-6 content. Reply with JSON only.";

export function buildPrompt(items) {
  const lines = items.map(
    (it, i) =>
      `${i}. [${it.source}/${it.kind}] ${it.title}` +
      (it.author ? ` - ${it.author}` : "") +
      (it.metric ? ` (${it.metric} ${it.metric_label})` : ""),
  );
  return (
    `Finds:\n${lines.join("\n")}\n\n` +
    `Return a JSON array, one object per find:\n` +
    `[{"i": 0, "score": 0-100, "category": "news|leak|clip|meme|guide|other", "new_info": true|false, ` +
    `"angle": "Short idea, max 14 words"}]\n/no_think`
  );
}

export function extractText(out) {
  if (typeof out === "string") return out;
  if (out?.response !== undefined) return typeof out.response === "string" ? out.response : JSON.stringify(out.response);
  if (out?.choices?.[0]?.message?.content) return out.choices[0].message.content;
  if (out?.result) return extractText(out.result);
  return JSON.stringify(out);
}

export function parseScores(text) {
  const clean = text.replace(/<think>[\s\S]*?<\/think>/g, "");
  const m = clean.match(/\[[\s\S]*\]/);
  if (!m) throw new Error("Qwen gave no JSON list");
  const arr = JSON.parse(m[0]);
  if (!Array.isArray(arr)) throw new Error("Qwen answer is not a list");
  return arr;
}

async function runQwen(env, messages) {
  const model = env.QWEN_MODEL || DEFAULT_MODEL;
  try {
    // low reasoning = far fewer tokens = stays inside the free daily allowance
    return await env.AI.run(model, { messages, max_tokens: 2500, reasoning_effort: "low" });
  } catch (err) {
    if (!/reasoning/i.test(String(err))) throw err;
    return env.AI.run(model, { messages, max_tokens: 2500 });
  }
}

/** Gives every item a score. Only the top `limit` (by rules) are sent to Qwen. */
export async function scoreItems(env, items, { limit = 30, batch = 15, now = Date.now() } = {}) {
  for (const it of items) {
    it.score = ruleScore(it, now);
    it.scored_by = "rules";
    it.category = it.kind === "clip" ? "clip" : it.kind === "news" ? "news" : "other";
    it.new_info = 0;
    it.angle = "";
  }
  if (!env.AI) return { aiErrors: ["no AI binding"] };

  const top = [...items].sort((a, b) => b.score - a.score).slice(0, limit);
  const aiErrors = [];
  for (let start = 0; start < top.length; start += batch) {
    const group = top.slice(start, start + batch);
    try {
      const out = await runQwen(env, [
        { role: "system", content: SYSTEM },
        { role: "user", content: buildPrompt(group) },
      ]);
      for (const s of parseScores(extractText(out))) {
        const it = group[Number(s.i)];
        if (!it) continue;
        const score = Number(s.score);
        if (Number.isFinite(score)) it.score = Math.round(Math.max(0, Math.min(100, score)));
        if (s.category) it.category = String(s.category).slice(0, 20);
        it.new_info = s.new_info ? 1 : 0;
        it.angle = String(s.angle || "").slice(0, 160);
        it.scored_by = "qwen";
      }
    } catch (err) {
      aiErrors.push(String(err?.message || err).slice(0, 200));
    }
  }
  return { aiErrors };
}
