"""Builds the on-screen text as an .ass subtitle file (rendered by ffmpeg/libass).

Styles: big word-by-word captions (current word yellow), the hook at the top,
a "GTA 6 NEWS" banner and a small source/streamer credit at the bottom."""

from __future__ import annotations

import re

W, H = 1080, 1920
FONT = "Anton"  # downloaded by the workflow; libass falls back to a bold sans if missing

HEADER = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{FONT},96,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,1,0,0,0,100,100,1,0,1,7,3,2,70,70,560,1
Style: Hook,{FONT},74,&H00FFFFFF,&H00FFFFFF,&H00952DFF,&H00952DFF,1,0,0,0,100,100,0,0,3,18,0,8,80,80,250,1
Style: Banner,{FONT},52,&H00000000,&H00000000,&H0000D4FF,&H0000D4FF,1,0,0,0,100,100,4,0,3,12,0,8,80,80,120,1
Style: Credit,{FONT},40,&H00E6E6E6,&H00E6E6E6,&H00000000,&H96000000,0,0,0,0,100,100,1,0,1,3,0,2,60,60,130,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

YELLOW = r"{\c&H00E5FF&}"  # ASS colours are BGR -> bright yellow
WHITE = r"{\c&HFFFFFF&}"


def ts(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int(seconds % 3600 // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text).replace("{", "(").replace("}", ")").replace("\\", "/")).strip()


def even_timing(text: str, duration: float, start: float = 0.0) -> list[dict]:
    """Fallback when there are no real word timings: spread words by length."""
    words = clean(text).split()
    if not words:
        return []
    weights = [len(w) + 2 for w in words]
    total = sum(weights)
    out, t = [], start
    for w, wt in zip(words, weights):
        d = duration * wt / total
        out.append({"word": w, "start": t, "end": t + d})
        t += d
    return out


def group_words(words: list[dict], size: int = 3) -> list[list[dict]]:
    groups, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= size or re.search(r"[.!?,;:]$", w["word"]):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    return groups


def caption_events(words: list[dict], upper: bool = True) -> list[str]:
    events = []
    for group in group_words(words):
        texts = [clean(w["word"]).upper() if upper else clean(w["word"]) for w in group]
        for i, w in enumerate(group):
            start = w["start"]
            end = group[i + 1]["start"] if i + 1 < len(group) else max(w["end"], start + 0.15)
            line = " ".join((YELLOW + t + WHITE) if j == i else t for j, t in enumerate(texts))
            events.append(f"Dialogue: 1,{ts(start)},{ts(end)},Caption,,0,0,0,,{line}")
    return events


def wrap(text: str, width: int = 20) -> str:
    words, lines, cur = clean(text).split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return r"\N".join(lines[:3])


def build_ass(duration: float, words: list[dict], hook: str = "", credit: str = "", banner: str = "") -> str:
    end = ts(duration)
    lines = [HEADER]
    if banner:
        lines.append(f"Dialogue: 2,0:00:00.00,{end},Banner,,0,0,0,,{clean(banner).upper()}")
    if hook:
        lines.append(f"Dialogue: 2,0:00:00.00,{end},Hook,,0,0,0,,{wrap(hook).upper()}")
    if credit:
        lines.append(f"Dialogue: 2,0:00:00.00,{end},Credit,,0,0,0,,{clean(credit)}")
    lines += caption_events(words)
    return "\n".join(lines) + "\n"
