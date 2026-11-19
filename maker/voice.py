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
