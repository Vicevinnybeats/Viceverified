"""Where is the streamer's face? Config first (maker/streamers.json), else auto-detect with OpenCV.

Returns a crop box (x, y, w, h) in source pixels for the top 'facecam' panel, or None."""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import tempfile

CONFIG = os.path.join(os.path.dirname(__file__), "streamers.json")
PANEL_ASPECT = 1080 / 672  # top panel = 1080 x 672 (35% of 1920)


def configured(streamer: str) -> dict | None:
    try:
        with open(CONFIG, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return (data.get("streamers") or {}).get((streamer or "").lower())


def _frames(video: str, folder: str, count: int = 8) -> list[str]:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video],
                         capture_output=True, text=True)
    try:
        dur = float(out.stdout.strip())
    except ValueError:
        dur = 10.0
    paths = []
    for i in range(count):
        t = dur * (i + 0.5) / count
        p = os.path.join(folder, f"f{i}.jpg")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", video, "-frames:v", "1", p])
        if os.path.exists(p):
            paths.append(p)
    return paths


def detect(video: str) -> tuple[int, int, int, int] | None:
    """Median face box over several frames -> facecam crop with the panel's aspect ratio."""
    try:
        import cv2
    except ImportError:
        return None
    if not hasattr(cv2, "CascadeClassifier"):  # OpenCV 5 moved it out; requirements pin OpenCV 4
        return None
    cascade = cv2.CascadeClassifier(os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml"))
    boxes, size = [], None
    with tempfile.TemporaryDirectory() as tmp:
        for p in _frames(video, tmp):
            img = cv2.imread(p)
            if img is None:
                continue
            size = img.shape[1], img.shape[0]
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=(36, 36))
            if len(faces):
                boxes.append(max(faces, key=lambda b: b[2] * b[3]))
    if size is None or len(boxes) < 3:  # a face must be there in most frames, not a random match
        return None
    fx = statistics.median(b[0] for b in boxes)
    fy = statistics.median(b[1] for b in boxes)
    fw = statistics.median(b[2] for b in boxes)
    fh = statistics.median(b[3] for b in boxes)
    # a face that wanders across the whole frame is not a fixed facecam
    if statistics.pstdev([b[0] for b in boxes]) > fw * 1.5:
        return None
    return crop_around((fx, fy, fw, fh), size)


def crop_around(face, size) -> tuple[int, int, int, int]:
    fx, fy, fw, fh = face
    W, H = size
    h = min(H, max(fh * 3.2, 120))
    w = min(W, h * PANEL_ASPECT)
    h = w / PANEL_ASPECT
    cx, cy = fx + fw / 2, fy + fh / 2 + fh * 0.25
    x = min(max(0, cx - w / 2), W - w)
    y = min(max(0, cy - h / 2), H - h)
    return int(x) // 2 * 2, int(y) // 2 * 2, int(w) // 2 * 2, int(h) // 2 * 2


def facecam_box(video: str, streamer: str, size: tuple[int, int]) -> tuple[tuple[int, int, int, int] | None, str]:
    """(box, how) - how = 'config', 'auto' or 'none'."""
    cfg = configured(streamer)
    if cfg and all(k in cfg for k in ("x", "y", "w", "h")):
        W, H = size
        return (int(cfg["x"] * W) // 2 * 2, int(cfg["y"] * H) // 2 * 2,
                int(cfg["w"] * W) // 2 * 2, int(cfg["h"] * H) // 2 * 2), "config"
    if cfg and cfg.get("facecam") is False:
        return None, "config"
    box = detect(video)
    return box, ("auto" if box else "none")
