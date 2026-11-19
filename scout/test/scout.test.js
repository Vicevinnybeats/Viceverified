import assert from "node:assert/strict";
import test from "node:test";

import { collect, dailyReport, recentItems } from "../src/index.js";
import { buildPrompt, extractText, parseScores, ruleScore, scoreItems } from "../src/rank.js";
import { buildReport } from "../src/report.js";
import { parseReddit, parseRss, parseTwitchClips } from "../src/sources.js";
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
    if (url.includes("news.google.com")) return new Response(RSS);
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
    assert.equal(first.newItems.length, 2); // both Google News queries return the same 2 stories -> de-duplicated
    assert.match(first.run.errors.reddit, /403/);
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
