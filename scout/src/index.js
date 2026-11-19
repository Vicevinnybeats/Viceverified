// Viceverified Daily Scout - a free Cloudflare Worker.
//
// Twice a day it checks Google News, Rockstar, Reddit, YouTube and Twitch for
// GTA 6 news and clips, lets Qwen score them, and remembers everything in D1.
// Every morning it writes the list to GitHub: reports/scout/YYYY-MM-DD.md
//
//   GET  /                     today's list (live, Markdown)
//   GET  /api/items?hours=24   finds as JSON (filters: status, kind, min_score)
//   POST /api/items/<id>       {"status": "used" | "skip" | "new"}   (needs SCOUT_KEY)
//   POST /api/run[?report=1]   run the Scout now                    (needs SCOUT_KEY)
//   POST /api/write            Qwen writes a Short script           (needs SCOUT_KEY)
//   POST /api/tts              backup AI voice (mp3)                (needs SCOUT_KEY)
//   POST /api/transcribe       word timings for captions            (needs SCOUT_KEY)
import { scoreItems } from "./rank.js";
import { buildReport, shortSummary } from "./report.js";
import { collectAll } from "./sources.js";
import { notify, saveToGitHub } from "./deliver.js";
import { dayString, sha1, titleKey } from "./util.js";
import { speak, transcribe, writeScript } from "./maker-api.js";
import { kvGet, kvPut, privacyPage, termsPage, tiktokCallback, tiktokLogin } from "./accounts.js";

const REPORT_CRON = "13 6 * * *"; // the morning run also writes the daily report

async function existing(db, column, values) {
  const found = new Set();
  for (let i = 0; i < values.length; i += 90) {
    const part = values.slice(i, i + 90);
    const q = `SELECT ${column} AS v FROM items WHERE ${column} IN (${part.map(() => "?").join(",")})`;
    const { results } = await db.prepare(q).bind(...part).all();
    results.forEach((r) => found.add(r.v));
  }
  return found;
}

export async function collect(env, now = new Date()) {
  const run = await collectAll(env, now);

  // de-duplicate: same link, or the same story from several sites
  const seen = new Set();
  const fresh = [];
  for (const it of run.items) {
    it.id = await sha1(it.url);
    it.title_key = titleKey(it.title);
    const key = it.kind === "clip" ? it.id : it.title_key || it.id;
    if (seen.has(it.id) || seen.has(key)) continue;
    seen.add(it.id);
    seen.add(key);
    fresh.push(it);
  }
  const knownIds = await existing(env.DB, "id", fresh.map((i) => i.id));
  const keys = fresh.filter((i) => i.kind !== "clip" && i.title_key).map((i) => i.title_key);
  const knownKeys = await existing(env.DB, "title_key", keys);
  const newItems = fresh.filter((i) => !knownIds.has(i.id) && !(i.kind !== "clip" && knownKeys.has(i.title_key)));

  const { aiErrors } = await scoreItems(env, newItems, { limit: Number(env.AI_MAX_ITEMS || 30), now: now.getTime() });
  run.aiErrors = aiErrors;

  const foundAt = now.toISOString();
  const insert = env.DB.prepare(
    `INSERT OR IGNORE INTO items (id, title_key, source, kind, title, url, author, published_at, found_at,
      metric, metric_label, thumbnail, score, category, new_info, angle, scored_by)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  );
  const stmts = newItems.map((i) =>
    insert.bind(i.id, i.title_key, i.source, i.kind, i.title, i.url, i.author || "", i.published_at, foundAt,
      i.metric || 0, i.metric_label || "", i.thumbnail || "", i.score, i.category, i.new_info, i.angle, i.scored_by),
  );
  stmts.push(
    env.DB.prepare("INSERT INTO runs (at, found, new_items, errors) VALUES (?, ?, ?, ?)").bind(
      foundAt, run.items.length, newItems.length, JSON.stringify({ ...run.errors, ai: aiErrors }),
    ),
  );
  await env.DB.batch(stmts);
  return { run, newItems };
}

export async function recentItems(env, { hours = 24, status, kind, minScore = 0, now = new Date() } = {}) {
  const since = new Date(now.getTime() - hours * 3_600_000).toISOString();
  let q = "SELECT * FROM items WHERE found_at >= ? AND score >= ?";
  const args = [since, minScore];
  if (status) {
    q += " AND status = ?";
    args.push(status);
  } else q += " AND status != 'skip'";
  if (kind) {
    q += " AND kind = ?";
    args.push(kind);
  }
  q += " ORDER BY score DESC LIMIT 300";
  return (await env.DB.prepare(q).bind(...args).all()).results;
}

async function lastRun(env) {
  return env.DB.prepare("SELECT * FROM runs ORDER BY id DESC LIMIT 1").first();
}

export async function dailyReport(env, now = new Date(), runInfo) {
  const day = dayString(now);
  const items = await recentItems(env, { hours: 24, now });
  const run = runInfo || { sources: [], errors: JSON.parse((await lastRun(env))?.errors || "{}") };
  const md = buildReport({ day, items, run });
  let link = "";
  if (env.GITHUB_TOKEN) link = await saveToGitHub(env, `reports/scout/${day}.md`, md, `Scout report ${day}`);
  await notify(env, shortSummary({ day, items }) + (link ? `\n\nFull list: ${link}` : ""));
  return { day, count: items.length, link, md };
}

function authorized(request, env) {
  return env.SCOUT_KEY && request.headers.get("Authorization") === `Bearer ${env.SCOUT_KEY}`;
}

// never let a browser show an old copy of a page
const NO_CACHE = { "Cache-Control": "no-store, max-age=0" };
const json = (data, status = 200) =>
  new Response(JSON.stringify(data, null, 2), { status, headers: { "Content-Type": "application/json", ...NO_CACHE } });

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(
      (async () => {
        const { run } = await collect(env);
        if (event.cron === REPORT_CRON) await dailyReport(env, new Date(), run);
      })(),
    );
  },

  async fetch(request, env) {
    const url = new URL(request.url);
    try {
      if (request.method === "GET" && url.pathname === "/") {
        const items = await recentItems(env, { hours: 24 });
        const last = await lastRun(env);
        const run = {
          sources: ["live view"],
          errors: last ? JSON.parse(last.errors || "{}") : {},
          twitch: Boolean(env.TWITCH_CLIENT_ID),
          lastRunAt: last?.at || "",
        };
        if (run.errors.ai) {
          run.aiErrors = run.errors.ai;
          delete run.errors.ai;
        }
        const md = buildReport({ day: dayString(), items, run });
        return new Response(md, { headers: { "Content-Type": "text/plain; charset=utf-8", ...NO_CACHE } });
      }
      // Browser-friendly "run now": /run?key=YOUR_SCOUT_KEY
      // Site-verification files (TikTok "Verify URL properties", Meta, Google): stored in D1 kv as verify:<file>
      const verifyMatch = url.pathname.match(/^\/([A-Za-z0-9_.-]{3,80}\.(?:txt|html))$/);
      if (request.method === "GET" && verifyMatch) {
        const body = await kvGet(env, `verify:${verifyMatch[1]}`);
        if (body !== null) return new Response(body, { headers: { "Content-Type": "text/plain; charset=utf-8" } });
      }
      if (request.method === "GET" && url.pathname === "/terms") return termsPage();
      if (request.method === "GET" && url.pathname === "/privacy") return privacyPage();
      if (request.method === "GET" && url.pathname === "/tiktok/login") return tiktokLogin(request, env);
      if (request.method === "GET" && url.pathname === "/tiktok/callback") return tiktokCallback(request, env);
      const stateMatch = url.pathname.match(/^\/api\/state\/([a-z0-9_-]{1,40})$/);
      if (stateMatch && (request.method === "GET" || request.method === "PUT")) {
        if (!authorized(request, env)) return json({ error: "missing or wrong SCOUT_KEY" }, 401);
        const key = `state:${stateMatch[1]}`;
        if (request.method === "GET") {
          const value = await kvGet(env, key);
          return new Response(value || "{}", { headers: { "Content-Type": "application/json", ...NO_CACHE } });
        }
        const text = await request.text();
        JSON.parse(text); // must be valid JSON
        await kvPut(env, key, text);
        return json({ ok: true });
      }
      if (request.method === "GET" && url.pathname === "/run") {
        if (!env.SCOUT_KEY || url.searchParams.get("key") !== env.SCOUT_KEY) {
          return new Response("Wrong or missing key. Use /run?key=YOUR_SCOUT_KEY", { status: 401, headers: NO_CACHE });
        }
        const { run, newItems } = await collect(env);
        const report = await dailyReport(env, new Date(), run);
        const problems = Object.entries(run.errors).map(([k, v]) => `  - ${k}: ${v}`).join("\n");
        const ai = (run.aiErrors || []).map((e) => `  - ${e}`).join("\n");
        const text =
          `✅ Scout ran.\n\nNew finds: ${newItems.length}\n` +
          `Saved to GitHub: ${report.link || "no (GITHUB_TOKEN missing?)"}\n` +
          (problems ? `\nSources with problems:\n${problems}\n` : "") +
          (ai ? `\nQwen problems:\n${ai}\n` : "") +
          `\nOpen ${url.origin}/ to see the list.`;
        return new Response(text, { headers: { "Content-Type": "text/plain; charset=utf-8", ...NO_CACHE } });
      }
      if (request.method === "GET" && url.pathname === "/api/items") {
        const items = await recentItems(env, {
          hours: Math.min(Number(url.searchParams.get("hours") || 24), 24 * 30),
          status: url.searchParams.get("status") || undefined,
          kind: url.searchParams.get("kind") || undefined,
          minScore: Number(url.searchParams.get("min_score") || 0),
        });
        return json({ count: items.length, items });
      }
      if (request.method === "POST" && url.pathname.startsWith("/api/")) {
        if (!authorized(request, env)) return json({ error: "missing or wrong SCOUT_KEY" }, 401);
        if (url.pathname === "/api/run") {
          const { run, newItems } = await collect(env);
          const report = url.searchParams.get("report") ? await dailyReport(env, new Date(), run) : null;
          return json({ new_items: newItems.length, errors: run.errors, ai_errors: run.aiErrors, report: report?.link });
        }
        if (url.pathname === "/api/write") return json(await writeScript(env, await request.json()));
        if (url.pathname === "/api/tts") {
          const { text, speaker } = await request.json();
          if (!text) return json({ error: "text is required" }, 400);
          return speak(env, text, speaker);
        }
        if (url.pathname === "/api/transcribe") {
          const audio = await request.arrayBuffer();
          if (!audio.byteLength) return json({ error: "send the audio file as the request body" }, 400);
          if (audio.byteLength > 4_000_000) return json({ error: "audio too big (max 4 MB)" }, 413);
          return json(await transcribe(env, audio));
        }
        const m = url.pathname.match(/^\/api\/items\/([a-f0-9]{16})$/);
        if (m) {
          const { status } = await request.json();
          if (!["new", "used", "skip"].includes(status)) return json({ error: "status must be new, used or skip" }, 400);
          await env.DB.prepare("UPDATE items SET status = ? WHERE id = ?").bind(status, m[1]).run();
          return json({ ok: true });
        }
      }
      return json({ error: "not found" }, 404);
    } catch (err) {
      return json({ error: String(err?.message || err) }, 500);
    }
  },
};
