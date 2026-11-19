import assert from "node:assert/strict";
import test from "node:test";

import { collect, dailyReport, recentItems } from "../src/index.js";
import { buildPrompt, extractText, parseScores, ruleScore, scoreItems } from "../src/rank.js";
import { buildReport } from "../src/report.js";
import { NEWS_FEEDS, bingNews, parseFeed, parseReddit, parseRss, parseTwitchClips, reddit } from "../src/sources.js";
import { decode, titleKey } from "../src/util.js";

const RSS = `<rss><channel>
<item><title>GTA 6 launch breaks PlayStation Store record - IGN</title>
<link>https://news.google.com/a1</link><pubDate>Wed, 19 Nov 2026 10:00:00 GMT</pubDate>
<source url="https://ign.com">IGN</source></item>
<item><title><![CDATA[Rockstar confirms GTA VI &amp; Online update]]></title>
<link>https://news.google.com/a2</link><pubDate>Wed, 19 Nov 2026 08:00:00 GMT</pubDate></item>
</channel></rss>`;

test("parses Google News RSS", () => {
  const items = parseRss(RSS);
  assert.equal(items.length, 2);
  assert.equal(items[0].author, "IGN");
  assert.equal(items[1].title, "Rockstar confirms GTA VI & Online update");
  assert.equal(items[0].published_at, "2026-11-19T10:00:00.000Z");
});

test("decodes entities and strips tags", () => {
  assert.equal(decode("A &amp; B &#39;x&#39; <b>bold</b> &#x1F600;"), "A & B 'x' bold 😀");
});

test("same story from two sites gets the same title key", () => {
  assert.equal(
    titleKey("GTA 6 launch breaks PlayStation Store record - IGN"),
    titleKey("GTA 6 Launch Breaks PlayStation Store Record! - Kotaku"),
  );
});

test("parses reddit and twitch", () => {
  const r = parseReddit({ data: { children: [
    { data: { title: "Map &amp; size", permalink: "/r/GTA6/x", subreddit: "GTA6", created_utc: 1795000000, score: 5400 } },
    { data: { title: "pinned", stickied: true, permalink: "/y", created_utc: 1 } },
  ] } });
  assert.equal(r.length, 1);
  assert.equal(r[0].title, "Map & size");
  assert.equal(r[0].metric, 5400);
  const t = parseTwitchClips({ data: [{ title: "insane chase", url: "https://clips.twitch.tv/x", broadcaster_name: "xQc",
    created_at: "2026-11-19T12:00:00Z", view_count: 81000 }] });
  assert.equal(t[0].kind, "clip");
  assert.equal(t[0].author, "xQc");
});

test("rule score prefers fresh, hot, popular", () => {
  const now = Date.parse("2026-11-19T12:00:00Z");
  const hot = ruleScore({ title: "GTA 6 map leak confirmed", published_at: "2026-11-19T10:00:00Z", metric: 50000, kind: "post" }, now);
  const cold = ruleScore({ title: "Best cars ranked", published_at: "2026-11-10T10:00:00Z", metric: 0, kind: "news" }, now);
  assert.ok(hot > cold);
  assert.ok(hot <= 100 && cold >= 0);
});

test("reads Qwen answers in every format", () => {
  assert.equal(extractText({ response: "a" }), "a");
  assert.equal(extractText({ choices: [{ message: { content: "b" } }] }), "b");
  const arr = parseScores('<think>[nope]</think>Here: [{"i":0,"score":91,"angle":"x"}]');
  assert.equal(arr[0].score, 91);
  assert.match(buildPrompt([{ source: "twitch", kind: "clip", title: "T", metric: 5, metric_label: "views" }]), /0\. \[twitch\/clip\] T/);
});

test("Qwen scores override rules; failures fall back to rules", async () => {
  const items = [
    { source: "reddit", kind: "post", title: "A", published_at: new Date().toISOString(), metric: 1 },
    { source: "reddit", kind: "post", title: "B", published_at: new Date().toISOString(), metric: 1 },
  ];
  const calls = [];
  const env = { AI: { run: async (model, input) => {
    calls.push(input);
    return { choices: [{ message: { content: '[{"i":0,"score":95,"category":"leak","new_info":true,"angle":"Do it"}]' } }] };
  } } };
  await scoreItems(env, items);
  const a = items.find((i) => i.title === "A");
  assert.equal(a.score, 95);
  assert.equal(a.scored_by, "qwen");
  assert.equal(calls[0].reasoning_effort, "low");

  const broken = [{ source: "x", kind: "news", title: "C", published_at: new Date().toISOString() }];
  const { aiErrors } = await scoreItems({ AI: { run: async () => { throw new Error("quota"); } } }, broken);
  assert.equal(broken[0].scored_by, "rules");
  assert.equal(aiErrors.length, 1);
});

test("retries without reasoning_effort if the model rejects it", async () => {
  let n = 0;
  const env = { AI: { run: async (m, input) => {
    n++;
    if (input.reasoning_effort) throw new Error("unknown property reasoning_effort");
    return { response: '[{"i":0,"score":70}]' };
  } } };
  const items = [{ source: "x", kind: "news", title: "D", published_at: new Date().toISOString() }];
  await scoreItems(env, items);
  assert.equal(n, 2);
  assert.equal(items[0].score, 70);
});

test("report has ideas, news and clips", () => {
  const md = buildReport({
    day: "2026-11-19",
    items: [
      { id: "aaaaaaaaaaaaaaaa", kind: "news", source: "google-news", title: "Record | launch", url: "https://n", author: "IGN", score: 88, angle: "GTA 6 broke every record", new_info: 1, metric: 0 },
      { id: "bbbbbbbbbbbbbbbb", kind: "clip", source: "twitch", title: "chase", url: "https://c", author: "xQc", score: 70, metric: 81000, metric_label: "views" },
    ],
    run: { sources: ["google-news", "twitch"], errors: { reddit: "HTTP 403" }, skipped: [] },
  });
  assert.match(md, /Make these Shorts today/);
  assert.match(md, /🆕 \[Record \/ launch\]/);
  assert.match(md, /\| 81\.0k \| \[chase\]/);
  assert.match(md, /reddit: HTTP 403/);
});

// ---- full run against a tiny fake D1 -------------------------------------------------
function fakeDB() {
  const rows = new Map();
  const runs = [];
  const stmt = (sql) => ({
    sql,
    args: [],
    bind(...a) { return { ...this, args: a }; },
    async all() {
      if (sql.includes("WHERE id IN")) return { results: this.args.filter((id) => rows.has(id)).map((v) => ({ v })) };
      if (sql.includes("WHERE title_key IN")) {
        const keys = new Set([...rows.values()].map((r) => r.title_key));
        return { results: this.args.filter((k) => keys.has(k)).map((v) => ({ v })) };
      }
      if (sql.startsWith("SELECT * FROM items")) {
        return { results: [...rows.values()].filter((r) => r.found_at >= this.args[0]).sort((a, b) => b.score - a.score) };
      }
      throw new Error(sql);
    },
    async first() { return runs.at(-1) || null; },
  });
  return {
    rows, runs,
    prepare: stmt,
    async batch(list) {
      for (const s of list) {
        if (s.sql.startsWith("INSERT OR IGNORE INTO items")) {
          const [id, title_key, source, kind, title, url, author, published_at, found_at, metric, metric_label,
            thumbnail, score, category, new_info, angle, scored_by] = s.args;
          if (!rows.has(id)) rows.set(id, { id, title_key, source, kind, title, url, author, published_at, found_at,
            metric, metric_label, thumbnail, score, category, new_info, angle, scored_by, status: "new" });
        } else runs.push({ errors: s.args[3] });
      }
    },
  };
}

test("collect stores new finds once and the report goes to GitHub", async () => {
  const realFetch = globalThis.fetch;
  const github = [];
  globalThis.fetch = async (url, opts = {}) => {
    url = String(url);
    if (url.includes("bing.com")) return new Response("busy", { status: 503 });
    if (url.includes("kotaku.com")) return new Response("down", { status: 500 });
    if (Object.values(NEWS_FEEDS).includes(url)) return new Response(RSS);
    if (url.includes("reddit.com")) return new Response("blocked", { status: 403 });
    if (url.includes("api.github.com")) {
      github.push({ url, method: opts.method || "GET", body: opts.body });
      return opts.method === "PUT"
        ? Response.json({ content: { html_url: "https://github.com/x/scout/2026-11-19.md" } })
        : new Response("", { status: 404 });
    }
    throw new Error(`unexpected fetch ${url}`);
  };
  try {
    const DB = fakeDB();
    const env = { DB, GITHUB_TOKEN: "t", AI: { run: async () => ({ response: '[{"i":0,"score":90,"angle":"Record launch"}]' }) } };
    const now = new Date("2026-11-19T12:00:00Z");
    const first = await collect(env, now);
    assert.equal(first.newItems.length, 2); // every site returns the same 2 stories -> de-duplicated
    assert.match(first.run.errors.reddit, /403.*REDDIT_CLIENT_ID/);
    assert.match(first.run.errors["bing-news"], /503/);
    assert.match(first.run.errors["news-sites (some)"], /Kotaku/);
    const again = await collect(env, now);
    assert.equal(again.newItems.length, 0);

    const items = await recentItems(env, { now });
    assert.equal(items.length, 2);
    const rep = await dailyReport(env, now, first.run);
    assert.equal(rep.link, "https://github.com/x/scout/2026-11-19.md");
    const put = github.find((g) => g.method === "PUT");
    assert.match(put.url, /contents\/reports\/scout\/2026-11-19\.md$/);
    const md = Buffer.from(JSON.parse(put.body).content, "base64").toString();
    assert.match(md, /GTA 6 Scout - 2026-11-19/);
  } finally {
    globalThis.fetch = realFetch;
  }
});

test("live page says when the Scout hasn't run, and /run needs the key", async () => {
  const { default: worker } = await import("../src/index.js");
  const DB = fakeDB();
  const env = { DB, SCOUT_KEY: "secret", TWITCH_CLIENT_ID: "x" };
  const page = await (await worker.fetch(new Request("https://s.dev/"), env)).text();
  assert.match(page, /hasn't run yet/);
  assert.match(page, /No new clips yet/);
  const denied = await worker.fetch(new Request("https://s.dev/run?key=nope"), env);
  assert.equal(denied.status, 401);
});

test("report without Twitch tells you to add it", () => {
  const md = buildReport({ day: "d", items: [], run: { twitch: false, sources: [], errors: {} } });
  assert.match(md, /add TWITCH_CLIENT_ID/);
});

const ATOM = `<feed><entry><title>GTA 6 PC port rumours heat up</title>
<link rel="alternate" href="https://polygon.com/gta6-pc"/><published>2026-11-19T09:00:00Z</published></entry>
<entry><title>Best Zelda mods</title><link href="https://polygon.com/zelda"/></entry></feed>`;

test("reads Atom feeds and keeps only GTA stories", () => {
  const items = parseFeed(ATOM, "Polygon");
  assert.equal(items.length, 1);
  assert.equal(items[0].url, "https://polygon.com/gta6-pc");
  assert.equal(items[0].author, "Polygon");
  const rss = parseFeed(RSS, "IGN");
  assert.equal(rss.length, 2);
  assert.equal(parseFeed("<rss><item><title>Halo news</title><link>https://x</link></item></rss>", "IGN").length, 0);
});

test("Bing links are unwrapped to the real article", async () => {
  const real = globalThis.fetch;
  globalThis.fetch = async () => new Response(`<rss><item><title>GTA 6 sales record</title>
    <link>http://www.bing.com/news/apiclick.aspx?ref=x&amp;url=https%3a%2f%2fign.com%2fgta6-sales&amp;c=1</link>
    <pubDate>Wed, 19 Nov 2026 10:00:00 GMT</pubDate></item></rss>`);
  try {
    const items = await bingNews("GTA 6");
    assert.equal(items[0].url, "https://ign.com/gta6-sales");
    assert.equal(items[0].source, "bing-news");
  } finally {
    globalThis.fetch = real;
  }
});

test("Reddit uses the app login when keys are set", async () => {
  const real = globalThis.fetch;
  const seen = [];
  globalThis.fetch = async (url, opts = {}) => {
    seen.push([String(url), opts.headers?.Authorization || ""]);
    if (String(url).includes("access_token")) return Response.json({ access_token: "tok" });
    return Response.json({ data: { children: [{ data: { title: "Hi", permalink: "/r/GTA6/h", subreddit: "GTA6", created_utc: 1795000000, score: 9 } }] } });
  };
  try {
    const items = await reddit("GTA6", "id", "sec");
    assert.equal(items.length, 1);
    assert.match(seen[0][1], /^Basic /);
    assert.equal(seen[1][0].startsWith("https://oauth.reddit.com/r/GTA6/top"), true);
    assert.equal(seen[1][1], "Bearer tok");
  } finally {
    globalThis.fetch = real;
  }
});

test("pages are never cached by the browser", async () => {
  const { default: worker } = await import("../src/index.js");
  const env = { DB: fakeDB(), SCOUT_KEY: "k" };
  for (const path of ["/", "/run?key=wrong", "/api/items"]) {
    const res = await worker.fetch(new Request(`https://s.dev${path}`), env);
    assert.match(res.headers.get("Cache-Control") || "", /no-store/, path);
  }
});

// ---- Short maker helpers ----------------------------------------------------------------
import { buildWritePrompt, parseObject, wordsFrom, writeScript } from "../src/maker-api.js";

test("script prompt uses only the article and flags unsafe topics", () => {
  const p = buildWritePrompt({ kind: "news", title: "Cast revealed", author: "Eurogamer", facts: "Rockstar named the cast." });
  assert.match(p, /Article text: Rockstar named the cast\./);
  assert.match(p, /"safe": true/);
  assert.match(buildWritePrompt({ kind: "clip", title: "LMAO", author: "xQc", metric: 5 }), /Stream clip from xQc/);
});

test("writeScript cleans Qwen's answer", async () => {
  const env = { AI: { run: async () => ({ response: '<think>x</think>{"hook":"Cast is OUT","voiceover":"Big news.","title":"T","hashtags":["#gta6"],"safe":false}' }) } };
  const s = await writeScript(env, { kind: "news", title: "Cast" });
  assert.equal(s.hook, "Cast is OUT");
  assert.equal(s.safe, false);
  assert.deepEqual(s.hashtags, ["#gta6"]);
  assert.throws(() => parseObject("nothing"), /no JSON/);
});

test("word timings from both Whisper formats", () => {
  assert.deepEqual(wordsFrom({ words: [{ word: " Hi", start: 0, end: 0.4 }] }), [{ word: "Hi", start: 0, end: 0.4 }]);
  assert.equal(wordsFrom({ segments: [{ words: [{ word: "a", start: 0, end: 1 }, { word: "b", start: 1, end: 2 }] }] }).length, 2);
  assert.deepEqual(wordsFrom({}), []);
});

test("maker routes need the key", async () => {
  const { default: worker } = await import("../src/index.js");
  const env = { DB: fakeDB(), SCOUT_KEY: "k", AI: { run: async () => ({ response: '{"hook":"h","voiceover":"v","title":"t"}' }) } };
  const denied = await worker.fetch(new Request("https://s.dev/api/write", { method: "POST", body: "{}" }), env);
  assert.equal(denied.status, 401);
  const ok = await worker.fetch(new Request("https://s.dev/api/write", {
    method: "POST", headers: { Authorization: "Bearer k" }, body: JSON.stringify({ kind: "news", title: "x" }) }), env);
  assert.equal((await ok.json()).hook, "h");
});

// ---- accounts: TikTok login, pages, token memory -----------------------------------------
function kvDB() {
  const kv = new Map();
  return {
    kv,
    prepare(sql) {
      return {
        args: [],
        bind(...a) { return { ...this, args: a }; },
        async first() { return kv.has(this.args[0]) ? { value: kv.get(this.args[0]) } : null; },
        async run() {
          if (sql.startsWith("INSERT INTO kv")) kv.set(this.args[0], this.args[1]);
          if (sql.startsWith("DELETE FROM kv")) kv.delete(this.args[0]);
          return {};
        },
      };
    },
  };
}

test("terms and privacy pages exist", async () => {
  const { default: worker } = await import("../src/index.js");
  for (const p of ["/terms", "/privacy"]) {
    const res = await worker.fetch(new Request(`https://s.dev${p}`), { DB: kvDB() });
    assert.equal(res.status, 200);
    assert.match(await res.text(), /Viceverified/);
  }
});

test("TikTok login: needs key, redirects, callback saves token for the Poster", async () => {
  const { default: worker } = await import("../src/index.js");
  const DB = kvDB();
  const env = { DB, SCOUT_KEY: "k", TIKTOK_CLIENT_KEY: "ck", TIKTOK_CLIENT_SECRET: "cs" };
  const bad = await worker.fetch(new Request("https://s.dev/tiktok/login?key=nope"), env);
  assert.match(await bad.text(), /Wrong or missing key/);

  const go = await worker.fetch(new Request("https://s.dev/tiktok/login?key=k"), env);
  assert.equal(go.status, 302);
  const auth = new URL(go.headers.get("Location"));
  assert.equal(auth.searchParams.get("redirect_uri"), "https://s.dev/tiktok/callback");
  assert.equal(auth.searchParams.get("scope"), "user.info.basic,video.upload,video.publish");
  const state = auth.searchParams.get("state");

  const real = globalThis.fetch;
  let sent;
  globalThis.fetch = async (url, opts) => { sent = Object.fromEntries(new URLSearchParams(opts.body)); return Response.json({ refresh_token: "RT", scope: "video.publish" }); };
  try {
    const done = await worker.fetch(new Request(`https://s.dev/tiktok/callback?code=C&state=${state}`), env);
    assert.match(await done.text(), /TikTok is connected/);
  } finally {
    globalThis.fetch = real;
  }
  assert.equal(sent.code, "C");
  assert.equal(sent.grant_type, "authorization_code");
  const saved = JSON.parse(DB.kv.get("state:poster"));
  assert.equal(saved.tiktok_refresh.value, "RT");
  // sha256("")[:16] - the Poster's marker for "no GitHub secret set"
  assert.equal(saved.tiktok_refresh.env_hash, "e3b0c44298fc1c14");
  assert.equal(DB.kv.has(`oauth:${state}`), false);

  const replay = await worker.fetch(new Request(`https://s.dev/tiktok/callback?code=C&state=${state}`), env);
  assert.match(await replay.text(), /expired or unknown/);
});

test("state memory needs the key and round-trips JSON", async () => {
  const { default: worker } = await import("../src/index.js");
  const env = { DB: kvDB(), SCOUT_KEY: "k" };
  const h = { Authorization: "Bearer k" };
  assert.equal((await worker.fetch(new Request("https://s.dev/api/state/poster"), env)).status, 401);
  await worker.fetch(new Request("https://s.dev/api/state/poster", { method: "PUT", headers: h, body: '{"a":1}' }), env);
  const got = await worker.fetch(new Request("https://s.dev/api/state/poster", { headers: h }), env);
  assert.deepEqual(await got.json(), { a: 1 });
});

test("serves site-verification files saved in the kv table", async () => {
  const { default: worker } = await import("../src/index.js");
  const DB = kvDB();
  DB.kv.set("verify:tiktokABC123.txt", "tiktok-developers-site-verification=ABC123");
  const ok = await worker.fetch(new Request("https://s.dev/tiktokABC123.txt"), { DB });
  assert.equal(await ok.text(), "tiktok-developers-site-verification=ABC123");
  const missing = await worker.fetch(new Request("https://s.dev/nothere.txt"), { DB, DB_: 1 });
  assert.equal(missing.status, 404);
});
