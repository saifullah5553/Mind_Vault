"""One-time YouTube sign-in.

Opens Google's consent page in your browser, catches the reply on this computer
and saves the refresh token to .env. The token is never printed, so it can't end
up in a chat or a log.

Before running, put YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in .env
(see docs/PUBLISHING.md).

Usage:
    python -m scripts.youtube_auth
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from core.config import ROOT_DIR

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.force-ssl",
          "https://www.googleapis.com/auth/yt-analytics.readonly"]
_CONSENT_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_CHANNEL_URL = "https://www.googleapis.com/youtube/v3/channels"
_WAIT_SECONDS = 300


def consent_url(client_id: str, redirect_uri: str, state: str, challenge: str) -> str:
    return _CONSENT_URL + "?" + urlencode({
        "client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
        "scope": " ".join(SCOPES), "state": state,
        # offline + consent: without both, Google returns no refresh token.
        "access_type": "offline", "prompt": "consent",
        "code_challenge": challenge, "code_challenge_method": "S256"})


def save_env(path: Path, key: str, value: str) -> None:
    """Set one line of .env and leave every other line as it was."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    entry = f"{key}={value}"
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = entry
            break
    else:
        lines.append(entry)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class _Reply(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        query = parse_qs(urlparse(self.path).query)
        if "code" in query or "error" in query:
            self.server.reply = query
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Done. You can close this tab and go back to Mind_Vault.")

    def log_message(self, *args) -> None:
        """Silent: the request line holds the one-time sign-in code."""


def _wait_for_reply(server: HTTPServer) -> dict:
    server.reply = None
    server.timeout = 5
    deadline = time.monotonic() + _WAIT_SECONDS
    while server.reply is None and time.monotonic() < deadline:
        server.handle_request()
    if server.reply is None:
        raise SystemExit("No reply from Google within 5 minutes. Run this again.")
    return server.reply


def main() -> None:
    client_id = os.getenv("YOUTUBE_CLIENT_ID")
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise SystemExit("Put YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in .env first "
                         "(see docs/PUBLISHING.md).")
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()

    server = HTTPServer(("127.0.0.1", 0), _Reply)      # this computer only
    redirect_uri = f"http://127.0.0.1:{server.server_port}/"
    url = consent_url(client_id, redirect_uri, state, challenge)
    print("Opening Google sign-in. If no browser opens, paste this address into one:\n" + url)
    webbrowser.open(url)
    reply = _wait_for_reply(server)
    server.server_close()

    if reply.get("state", [""])[0] != state:
        raise SystemExit("The reply didn't match this sign-in, so it was ignored. Run this again.")
    if "code" not in reply:
        raise SystemExit(f"Google refused the sign-in: {reply.get('error', ['unknown'])[0]}")

    resp = httpx.post(_TOKEN_URL, timeout=30, data={
        "client_id": client_id, "client_secret": client_secret, "code": reply["code"][0],
        "code_verifier": verifier, "redirect_uri": redirect_uri,
        "grant_type": "authorization_code"})
    if resp.status_code != 200:
        raise SystemExit(f"Google refused the token request ({resp.status_code}).")
    tokens = resp.json()
    if not tokens.get("refresh_token"):
        raise SystemExit("Google sent no refresh token. Run this again and accept every box.")

    save_env(ROOT_DIR / ".env", "YOUTUBE_REFRESH_TOKEN", tokens["refresh_token"])
    channels = httpx.get(_CHANNEL_URL, timeout=30, params={"part": "snippet", "mine": "true"},
                         headers={"Authorization": f"Bearer {tokens['access_token']}"})
    names = [c["snippet"]["title"] for c in channels.json().get("items", [])] \
        if channels.status_code == 200 else []
    print("Saved to .env.")
    print(f"Uploads will go to: {', '.join(names)}" if names
          else "Couldn't read the channel name. Check the channel before uploading.")


if __name__ == "__main__":
    main()
