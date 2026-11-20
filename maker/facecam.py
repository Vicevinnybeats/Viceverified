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


MODEL = os.path.join(os.path.dirname(__file__), "models", "yunet.onnx")  # OpenCV Zoo YuNet, MIT


def _yunet(cv2, w: int, h: int):
    if not hasattr(cv2, "FaceDetectorYN") or not os.path.exists(MODEL):
        return None
    try:
        return cv2.FaceDetectorYN.create(MODEL, "", (w, h), 0.6)
    except Exception:
        return None


def pick_facecam(samples: list[list[tuple[float, float, float, float]]], size: tuple[int, int]):
    """The real webcam = a face in the same spot in most frames that moves a little (a live person).
    Faces in cutscenes/the game wander around; a paused video's face never moves; a full-screen
    webcam face is too big. Idea from gta6-clipper (MIT). Returns a face box (x, y, w, h) or None."""
    W, H = size
    cells: dict[tuple[int, int], list] = {}
    for faces in samples:
        seen = set()
        for x, y, w, h in faces:
            c = (int((x + w / 2) / W * 8), int((y + h / 2) / H * 6))
            if c not in seen:
                seen.add(c)
                cells.setdefault(c, []).append((float(x), float(y), float(w), float(h)))
    best = None
    for c, boxes in cells.items():
        if len(boxes) < max(3, len(samples) * 0.4):
            continue
        cx = [b[0] + b[2] / 2 for b in boxes]
        cy = [b[1] + b[3] / 2 for b in boxes]
        jitter = (statistics.pstdev(cx) + statistics.pstdev(cy)) / 2
        fw = statistics.median(b[2] for b in boxes)
        if jitter < 0.5 or fw > W * 0.12 or fw < W * 0.02:  # frozen, full-screen cam, or too tiny to fill the panel
            continue
        score = len(boxes) + c[1] * 2 + (3 if c[0] in (0, 1, 6, 7) else 0)  # cams sit low and in corners
        if not best or score > best[0]:
            best = (score, boxes)
    if not best:
        return None
    b = best[1]
    return tuple(statistics.median(v[i] for v in b) for i in range(4))


def detect(video: str, count: int = 16) -> tuple[int, int, int, int] | None:
    """Facecam crop with the panel's aspect ratio, or None (then the whole game screen is shown)."""
    try:
        import cv2
    except ImportError:
        return None
    samples, size = [], None
    with tempfile.TemporaryDirectory() as tmp:
        for p in _frames(video, tmp, count):
            img = cv2.imread(p)
            if img is None:
                continue
            H, W = img.shape[:2]
            size = (W, H)
            s = 960 / W
            small = cv2.resize(img, (960, int(H * s)))
            det = _yunet(cv2, 960, int(H * s))
            faces = []
            if det is not None:
                _, fs = det.detect(small)
                faces = [] if fs is None else [tuple(float(v) / s for v in f[:4]) for f in fs]
            elif hasattr(cv2, "CascadeClassifier"):  # fallback: older Haar detector
                casc = cv2.CascadeClassifier(os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml"))
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                faces = [tuple(float(v) for v in b) for b in casc.detectMultiScale(gray, 1.1, 6, minSize=(36, 36))]
            samples.append(faces)
    if size is None:
        return None
    face = pick_facecam(samples, size)
    return crop_around(face, size) if face else None


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
