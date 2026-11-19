// Turns the day's finds into a readable Markdown list.

const esc = (s = "") => String(s).replace(/\|/g, "/").replace(/\n/g, " ").trim();

function fmtNum(n) {
  if (!n) return "";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

export function buildReport({ day, items, run }) {
  const clips = items.filter((i) => i.kind === "clip").sort((a, b) => b.metric - a.metric);
  const other = items.filter((i) => i.kind !== "clip").sort((a, b) => b.score - a.score);
  const ideas = items.filter((i) => i.angle && i.score >= 60).sort((a, b) => b.score - a.score).slice(0, 8);
  const newInfo = items.filter((i) => i.new_info).length;

  const out = [];
  out.push(`# 🔍 GTA 6 Scout - ${day}`, "");
  out.push(
    `**${items.length} new finds** in the last 24h · ${newInfo} with genuinely new info · ` +
      `${clips.length} stream clips`,
    "",
  );

  if (ideas.length) {
    out.push("## 💡 Make these Shorts today", "");
    ideas.forEach((i, n) => out.push(`${n + 1}. **${esc(i.angle)}** (score ${i.score}) - [source](${i.url})`));
    out.push("");
  }

  out.push("## 📰 News & posts (best first)", "");
  if (other.length) {
    out.push("| Score | What | Source | ID |", "|---|---|---|---|");
    for (const i of other.slice(0, 25)) {
      const extra = i.metric ? ` · ${fmtNum(i.metric)} ${i.metric_label}` : "";
      const flag = i.new_info ? "🆕 " : "";
      out.push(`| ${i.score} | ${flag}[${esc(i.title)}](${i.url}) | ${esc(i.author || i.source)}${extra} | \`${i.id}\` |`);
    }
  } else out.push("_Nothing new._");
  out.push("");

  out.push("## 🎬 Top stream clips (for the Clipper)", "");
  if (clips.length) {
    out.push("| Views | Clip | Streamer | ID |", "|---|---|---|---|");
    for (const i of clips.slice(0, 15)) {
      out.push(`| ${fmtNum(i.metric)} | [${esc(i.title)}](${i.url}) | ${esc(i.author)} | \`${i.id}\` |`);
    }
  } else out.push("_No clips (add TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET to turn this on)._");
  out.push("");

  out.push("---", "");
  const errs = Object.entries(run.errors || {});
  out.push(`Sources checked: ${(run.sources || []).join(", ") || "-"}`);
  if (run.skipped?.length) out.push(`Not set up: ${run.skipped.join(", ")}`);
  if (errs.length) out.push(`Problems: ${errs.map(([k, v]) => `${k}: ${v}`).join(" · ")}`);
  if (run.aiErrors?.length) out.push(`Qwen problems: ${run.aiErrors.join(" · ")}`);
  out.push("");
  return out.join("\n");
}

export function shortSummary({ day, items }) {
  const top = [...items].sort((a, b) => b.score - a.score).slice(0, 5);
  return [
    `🔍 GTA 6 Scout ${day}: ${items.length} new finds`,
    ...top.map((i) => `• ${i.score} - ${i.angle || i.title}\n  ${i.url}`),
  ].join("\n");
}
