"""The ViceVerified clip look (no blur anywhere):

  ┌──────────────────────┐  top 35%   streamer facecam (crop from config or auto-detected)
  │  HOOK (first 3 s)    │
  ├──────────────────────┤  bottom 65% gameplay, zooms in on the peak moment
  │   word-by-word       │            captions in the middle, keywords in yellow
  │   captions           │            chat messages pop up at the peak
  │ via @streamer   [VV] │
  └──────────────────────┘
No facecam found -> gameplay fills the whole 9:16 screen.
Audio normalised to -14 LUFS (YouTube/TikTok loudness)."""

from __future__ import annotations

import os
import re

from . import render
from .subs import FONT, group_words, ts
from .subs import clean as _clean

_EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]")


def clean(text: str) -> str:
    """Caption-safe text: the bold caption font has no emoji, so they are removed on screen."""
    return _clean(_EMOJI.sub("", str(text))).strip()

W, H = 1080, 1920
TOP_H = 672            # 35 %
BOTTOM_H = H - TOP_H   # 65 %
LOGO = os.path.join(os.path.dirname(os.path.dirname(__file__)), "brand", "viceverified-icon-1024.png")
YELLOW, WHITE = r"{\c&H00E5FF&}", r"{\c&HFFFFFF&}"

STYLE_HEADER = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,{FONT},92,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,1,0,1,9,4,8,60,60,90,1
Style: Caption,{FONT},94,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,1,0,0,0,100,100,1,0,1,8,3,5,70,70,0,1
Style: Via,{FONT},40,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,1,0,0,0,100,100,1,0,1,4,1,1,40,40,46,1
Style: Chat,{FONT},38,&H00FFFFFF,&H00FFFFFF,&H00000000,&HB4141414,0,0,0,0,100,100,0,0,3,10,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

KEYWORDS = {"no", "way", "wtf", "insane", "crazy", "what", "bro", "dead", "money", "police", "cops", "chase", "crash",
            "boom", "kill", "rockstar", "lucia", "jason", "vice", "gta", "million", "never", "biggest", "secret", "glitch"}


def is_keyword(word: str) -> bool:
    w = re.sub(r"[^a-z0-9$]", "", word.lower())
    return bool(w) and (w in KEYWORDS or any(c.isdigit() for c in w) or w.startswith("$") or len(w) >= 8)


def caption_events(words: list[dict], y: int) -> list[str]:
    """Word-by-word: the group stays on screen, the spoken word pops, keywords are yellow."""
    out = []
    for group in group_words(words, size=3):
        texts = [clean(w["word"]).upper() for w in group]
        for i, w in enumerate(group):
            start = w["start"]
            end = group[i + 1]["start"] if i + 1 < len(group) else max(w["end"], start + 0.2)
            parts = []
            for j, t in enumerate(texts):
                color = YELLOW if is_keyword(t) else WHITE
                pop = r"{\fscx112\fscy112}" if j == i else r"{\fscx100\fscy100}"
                parts.append(f"{pop}{color}{t}")
            out.append(f"Dialogue: 2,{ts(start)},{ts(end)},Caption,,0,0,0,,{{\\pos({W // 2},{y})}}" + " ".join(parts))
    return out


def chat_events(messages: list[dict], peak: float, top_of_gameplay: int) -> list[str]:
    """Chat bubbles slide in from the left at the peak, stacked, each visible ~2.5 s."""
    out = []
    for k, m in enumerate(messages[:5]):
        start = max(0.0, peak - 0.3 + k * 0.45)
        end = start + 2.6
        y = top_of_gameplay + 40 + k * 64
        user = clean(m.get("user") or "chat")[:16]
        text = clean(m.get("text") or "")[:40]
        if not text:
            continue
        out.append(f"Dialogue: 3,{ts(start)},{ts(end)},Chat,,0,0,0,,"
                   f"{{\\move(-420,{y},30,{y},0,180)\\fad(80,250)}}{{\\c&H00E5FF&}}{user}: {{\\c&HFFFFFF&}}{text}")
    return out


def wrap(text: str, width: int = 18) -> str:
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


def build_ass(duration: float, words: list[dict], hook: str, streamer: str, peak: float,
              chat: list[dict], split: bool) -> str:
    cap_y = TOP_H + 260 if split else int(H * 0.62)
    lines = [STYLE_HEADER]
    if hook:  # in the first frames, gone after ~3 s
        lines.append(f"Dialogue: 4,0:00:00.00,{ts(min(3.2, duration))},Hook,,0,0,0,,{{\\fad(0,250)}}{wrap(hook).upper()}")
    lines.append(f"Dialogue: 4,0:00:00.00,{ts(duration)},Via,,0,0,0,,via @{clean(streamer)}")
    lines += caption_events(words, cap_y)
    lines += chat_events(chat, peak, TOP_H if split else 300)
    return "\n".join(lines) + "\n"


def _zoom(peak: float) -> str:
    # quick push-in on the peak moment, back out after ~1.6 s
    return (f"zoompan=z='if(between(it,{max(0.0, peak - 0.25):.2f},{peak + 1.6:.2f}),min(zoom+0.025,1.18),"
            f"max(zoom-0.03,1))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:fps=30")


def render_clip(out: str, src: str, ass: str, start: float, length: float, peak: float,
                facecam: tuple[int, int, int, int] | None, size: tuple[int, int], fonts_dir: str | None = None) -> str:
    """Cut [start, start+length] from src and build the vertical Short. `peak` is relative to `start`."""
    sw, sh = size
    filters = []
    if facecam:
        fx, fy, fw, fh = facecam
        gw = int(sh * W / BOTTOM_H) // 2 * 2  # gameplay crop width with the bottom panel's aspect
        gx = max(0, (sw - gw) // 2)
        filters += [
            "[0:v]split=2[cam][game]",
            f"[cam]crop={fw}:{fh}:{fx}:{fy},scale={W}:{TOP_H}:flags=lanczos,setsar=1[top]",
            f"[game]crop={min(gw, sw)}:{sh}:{gx}:0,scale={W}:{BOTTOM_H}:flags=lanczos,"
            f"{_zoom(peak)}:s={W}x{BOTTOM_H},setsar=1[bottom]",
            "[top][bottom]vstack=inputs=2[stack]",
        ]
    else:
        gw = int(sh * 9 / 16) // 2 * 2
        filters += [f"[0:v]crop={min(gw, sw)}:{sh}:{max(0, (sw - gw) // 2)}:0,scale={W}:{H}:flags=lanczos,"
                    f"{_zoom(peak)}:s={W}x{H},setsar=1[stack]"]
    last = "stack"
    inputs = ["-ss", f"{start:.2f}", "-t", f"{length:.2f}", "-i", src]
    if os.path.exists(LOGO):
        inputs += ["-i", LOGO]
        filters.append("[1:v]scale=120:120,format=rgba,colorchannelmixer=aa=0.92[logo]")
        filters.append(f"[{last}][logo]overlay=W-w-34:H-h-34[withlogo]")
        last = "withlogo"
    filters.append(f"[{last}]{render._subs_filter(ass, fonts_dir)}[v]")
    cmd = ["ffmpeg", "-y", "-hide_banner", *inputs, "-filter_complex", ";".join(filters), "-map", "[v]"]
    if render.has_audio(src):
        cmd += ["-map", "0:a:0", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11"]
    else:
        cmd += ["-f", "lavfi", "-t", f"{length:.2f}", "-i", "anullsrc=r=44100:cl=stereo", "-map", f"{2 if os.path.exists(LOGO) else 1}:a"]
    cmd += ["-t", f"{length:.2f}", *render.ENCODE, out]
    render.run(cmd)
    return out


def video_size(path: str) -> tuple[int, int]:
    import subprocess

    outp = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                           "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip()
    w, h = (int(x) for x in outp.split(",")[:2])
    return w, h


def choose_window(duration: float, peak: float, min_len: float = 25, max_len: float = 45,
                  lead: float = 12) -> tuple[float, float]:
    """Start just before the action: ~12 s before the peak, 25-45 s long."""
    if duration <= max_len:
        return 0.0, duration
    start = max(0.0, min(peak - lead, duration - max_len))
    return start, max_len
