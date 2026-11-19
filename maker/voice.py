"""Voiceover: VoiceStudio first (https://github.com/debpalash/VoiceStudio), Cloudflare voice as backup.

VoiceStudio speaks the OpenAI-style API:  POST {url}/v1/audio/speech
  {"model": "tts-1", "voice": "alloy", "input": "...", "response_format": "mp3"}  -> mp3 bytes
In GitHub Actions the workflow starts VoiceStudio's Docker image on localhost:3900.
You can also point VOICESTUDIO_URL at your own VoiceStudio (e.g. with your cloned voice)."""

from __future__ import annotations

import time

import requests

from .config import Config


class VoiceError(RuntimeError):
    pass


def voicestudio_ready(cfg: Config, wait_seconds: int = 0) -> bool:
    if not cfg.voicestudio_url:
        return False
    deadline = time.time() + wait_seconds
    while True:
        try:
            r = requests.get(f"{cfg.voicestudio_url}/health", headers=_h(cfg), timeout=10)
            if r.ok:
                return True
        except requests.RequestException:
            pass
        if time.time() >= deadline:
            return False
        time.sleep(5)


def _h(cfg: Config) -> dict:
    return {"Authorization": f"Bearer {cfg.voicestudio_key}"} if cfg.voicestudio_key else {}


def voicestudio(cfg: Config, text: str, dest: str) -> str:
    body = {
        "model": cfg.voicestudio_model,
        "voice": cfg.voicestudio_voice,
        "input": text,
        "response_format": "mp3",
        "speed": cfg.voice_speed,
    }
    r = requests.post(f"{cfg.voicestudio_url}/v1/audio/speech", json=body, headers=_h(cfg), timeout=900)
    if not r.ok or not r.content or r.headers.get("Content-Type", "").startswith("application/json"):
        raise VoiceError(f"VoiceStudio HTTP {r.status_code}: {r.text[:300]}")
    with open(dest, "wb") as f:
        f.write(r.content)
    return dest


def speak(cfg: Config, scout, text: str, dest: str, log=print) -> tuple[str, str]:
    """Returns (path, which_voice)."""
    if cfg.voicestudio_url:
        try:
            voicestudio(cfg, text, dest)
            return dest, "VoiceStudio"
        except Exception as exc:
            log(f"  VoiceStudio failed, using the backup voice: {exc}")
    with open(dest, "wb") as f:
        f.write(scout.tts(text))
    return dest, "Cloudflare Aura (backup)"


def setup_voicestudio(cfg: Config, log=print) -> None:
    """Installs the voice model (KittenTTS by default) and records the licence acknowledgement
    for exactly that model - only when VOICESTUDIO_ACCEPT_LICENSE names it."""
    base, h = cfg.voicestudio_url, _h(cfg)
    repo = cfg.voicestudio_install
    if not repo:
        return
    r = requests.post(f"{base}/models/install", json={"repo_id": repo, "target": "local"}, headers=h, timeout=1800)
    log(f"install {repo}: HTTP {r.status_code} {r.text[:200]}")
    deadline = time.time() + 1200
    while time.time() < deadline:
        s = requests.get(f"{base}/models/install/status", headers=h, timeout=30)
        jobs = s.json().get("jobs", []) if s.ok else []
        if not any(j.get("repo_id") == repo for j in jobs):
            break
        time.sleep(5)
    if cfg.voicestudio_accept and cfg.voicestudio_accept == repo:
        d = requests.get(f"{base}/models/licenses/acceptance/{repo}", headers=h, timeout=30)
        info = d.json() if d.ok else {}
        log(f"licence for {repo}: {info.get('license')} - state {info.get('state')}")
        if info.get("fingerprint") and info.get("state") not in ("accepted", "not_required"):
            a = requests.post(f"{base}/models/licenses/accept", headers=h, timeout=30,
                              json={"repo_id": repo, "fingerprint": info["fingerprint"], "accepted": True})
            log(f"accepted licence acknowledgement for {repo}: HTTP {a.status_code} {a.text[:200]}")
