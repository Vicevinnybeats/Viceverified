"""One-time login helpers. Run these ON YOUR OWN PC (they open a browser).

    python -m poster auth google   -> prints GOOGLE_REFRESH_TOKEN
    python -m poster auth tiktok   -> prints TIKTOK_REFRESH_TOKEN
"""

from __future__ import annotations

import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from .config import Config
from .google import SCOPES, TOKEN_URL
from .http import TIMEOUT, check
from .tiktok import API as TIKTOK_API

GOOGLE_PORT = 8765


def google_login(cfg: Config) -> None:
    if not (cfg.google_client_id and cfg.google_client_secret):
        raise SystemExit("Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in your .env first (see SETUP.md step 2).")
    redirect = f"http://127.0.0.1:{GOOGLE_PORT}/"
    state = secrets.token_urlsafe(16)
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id": cfg.google_client_id,
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })
    got: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            got.update({k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h2>Done - you can close this tab and go back to the terminal.</h2>")

        def log_message(self, *args):
            pass

    print("Log in with Viceverified.HQ@gmail.com (the account that owns the YouTube channel).")
    print("If the browser doesn't open, paste this link:\n\n" + url + "\n")
    webbrowser.open(url)
    server = HTTPServer(("127.0.0.1", GOOGLE_PORT), Handler)
    while "code" not in got and "error" not in got:
        server.handle_request()
    if got.get("state") != state or "code" not in got:
        raise SystemExit(f"Login failed: {got.get('error', 'state mismatch')}")
    resp = requests.post(TOKEN_URL, timeout=TIMEOUT, data={
        "code": got["code"],
        "client_id": cfg.google_client_id,
        "client_secret": cfg.google_client_secret,
        "redirect_uri": redirect,
        "grant_type": "authorization_code",
    })
    token = check(resp, "Google token").json().get("refresh_token")
    if not token:
        raise SystemExit("Google didn't return a refresh token. Remove the app at "
                         "https://myaccount.google.com/permissions and run this again.")
    print("\n✅ Your GOOGLE_REFRESH_TOKEN (add it as a GitHub secret):\n\n" + token + "\n")


def tiktok_login(cfg: Config, redirect_uri: str) -> None:
    if not (cfg.tiktok_client_key and cfg.tiktok_client_secret):
        raise SystemExit("Set TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET in your .env first (see SETUP.md step 5).")
    state = secrets.token_urlsafe(16)
    url = "https://www.tiktok.com/v2/auth/authorize/?" + urlencode({
        "client_key": cfg.tiktok_client_key,
        "scope": "user.info.basic,video.publish,video.upload",
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
    })
    print("1) Open this link and allow access with your TikTok account:\n\n" + url + "\n")
    webbrowser.open(url)
    pasted = input("2) After allowing, your browser goes to your redirect page.\n"
                   "   Copy the FULL address from the address bar and paste it here:\n> ").strip()
    params = {k: v[0] for k, v in parse_qs(urlparse(pasted).query).items()}
    if params.get("state") != state or "code" not in params:
        raise SystemExit(f"Login failed: {params.get('error_description') or params.get('error') or 'no code in link'}")
    resp = requests.post(f"{TIKTOK_API}/oauth/token/", timeout=TIMEOUT,
                         headers={"Content-Type": "application/x-www-form-urlencoded"}, data={
                             "client_key": cfg.tiktok_client_key,
                             "client_secret": cfg.tiktok_client_secret,
                             "code": params["code"],
                             "grant_type": "authorization_code",
                             "redirect_uri": redirect_uri,
                         })
    data = check(resp, "TikTok token").json()
    if "refresh_token" not in data:
        raise SystemExit(f"TikTok login failed: {data}")
    print("\n✅ Your TIKTOK_REFRESH_TOKEN (add it as a GitHub secret):\n\n" + data["refresh_token"] + "\n")
