"""Loudness per second (ffmpeg ebur128) - finds the peak moment of a clip or VOD segment."""

from __future__ import annotations

import re
import subprocess

_M_RE = re.compile(r"t:\s*([\d.]+)\s+TARGET:.*?M:\s*(-?[\d.]+|-inf)")


def per_second(path: str) -> list[float]:
    """Momentary loudness (LUFS) for every second of audio."""
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-vn", "-af", "ebur128=peak=none",
                           "-f", "null", "-"], capture_output=True, text=True, timeout=900)
    per: dict[int, list[float]] = {}
    for t, m in _M_RE.findall(proc.stderr):
        if m == "-inf":
            continue
        per.setdefault(int(float(t)), []).append(float(m))
    if not per:
        return []
    last = max(per)
    # floor at -70: Twitch's muted (copyright) parts measure ~-140 and would fake huge "spikes"
    return [max(-70.0, max(per.get(i, [-70.0]))) for i in range(last + 1)]


def peak(levels: list[float], window: int = 120, jump_db: float = 8.0) -> dict:
    """The loudest moment, and whether it jumps >= jump_db above the 2-minute average."""
    if not levels:
        return {"t": 0, "lufs": None, "jump": 0.0, "spike": False}
    i = max(range(len(levels)), key=lambda k: levels[k])
    lo = max(0, i - window)
    base = [v for v in levels[lo:i] if v > -60] or [v for v in levels if v > -60] or levels
    avg = sum(base) / len(base)
    jump = levels[i] - avg
    return {"t": i, "lufs": round(levels[i], 1), "jump": round(jump, 1), "spike": jump >= jump_db}


def per_minute(levels: list[float]) -> list[float]:
    return [round(sum(levels[i:i + 60]) / len(levels[i:i + 60]), 1) for i in range(0, len(levels), 60)]
