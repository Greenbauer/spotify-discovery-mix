"""Spotify OAuth helpers: the scopes, the authorize URL, and token refresh.

Moved out of mix.py unchanged; mix.py re-exports every name here. oauth.py is
the separate one-time helper that runs the browser flow.
"""

from __future__ import annotations

from urllib.parse import urlencode

import requests

from http_client import UA

SPOTIFY_ACCOUNTS = "https://accounts.spotify.com/api/token"

SCOPES = [
    "playlist-read-private",
    "playlist-read-collaborative",
    "user-library-read",
    "playlist-modify-private",
    "playlist-modify-public",
    "user-read-recently-played",
    "user-read-currently-playing",
    "user-read-playback-state",
    "user-read-private",
]


def refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    resp = requests.post(
        SPOTIFY_ACCOUNTS,
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        auth=(client_id, client_secret),
        headers={"User-Agent": UA},
        timeout=30,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"token refresh -> {resp.status_code}: {resp.text[:400]}")
    token = resp.json().get("access_token")
    if not token:
        raise RuntimeError("token refresh returned no access_token")
    return token


def authorize_url(client_id: str, redirect_uri: str) -> str:
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": " ".join(SCOPES),
    }
    return "https://accounts.spotify.com/authorize?" + urlencode(params)
