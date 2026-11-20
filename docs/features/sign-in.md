# Sign in to Spotify once

`oauth.py` is the one-time, opt-in sign-in helper. It serves the callback on `http://127.0.0.1:8080/callback`, exchanges the code, and writes `SPOTIFY_REFRESH_TOKEN` (and `SPOTIFY_ACCESS_TOKEN`) into `.env` with mode 600. `mix.py print_auth_url` only prints the authorize URL and the scopes for doing it by hand. `mix.py` never starts a sign-in itself; the commands that reach Spotify use the refresh token.

## Surfaces

- script: `oauth.py`
- command: `print_auth_url`
- option: `--redirect-uri`
- source: `oauth.py`
- source: `spotify_auth.py`
- source: `mix.py`
- source: `.env.example`

## Reach

Register a Spotify developer app (Premium is needed for Dev Mode) with the redirect URI `http://127.0.0.1:8080/callback`, and put `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` in `.env`. Then run `.venv/bin/python oauth.py` and open the URL it writes to `/tmp/spotify-auth-url.txt`. To do it by hand, run `.venv/bin/python mix.py print_auth_url --redirect-uri http://127.0.0.1:8080/callback` and exchange the code yourself, as the README shows.

## Verify

- `mix.py::401 is retried once with a refreshed token`
- `mix.py::a stale token mints exactly one replacement`
- `tests/test_live_watch_limits.py::test_refused_refresh_token_is_an_auth_failure`

The `mix.py::` anchors are check messages inside `mix.py self_test`, which runs with no network.

1. With `.venv` set up (see [setup](setup.md)), make a new empty folder `D` and run `SPOTIFY_CLIENT_ID=example-client .venv/bin/python mix.py --env-file D/none.env --state-dir D print_auth_url`: it prints an `https://accounts.spotify.com/authorize?client_id=example-client...` URL with the URL-encoded redirect `redirect_uri=http%3A%2F%2F127.0.0.1%3A8080%2Fcallback`, the nine scopes, and `This script does not start a server or exchange the code.`, and exits 0.
2. With `.venv` set up (see [setup](setup.md)), make a new empty folder `D` and run `env -u SPOTIFY_CLIENT_ID .venv/bin/python mix.py --env-file D/none.env --state-dir D print_auth_url`: it prints `Set SPOTIFY_CLIENT_ID first. This command only prints a URL.` and exits 1.

Never run `oauth.py` as a check: it starts a server and a real sign-in.

re-walk: none -- the sign-in happens on Spotify's own page with your account; nothing here is safe to walk

## Gotchas

- `oauth.py` reads no arguments, so `oauth.py --help` starts the server too. It waits up to 10 minutes for the callback, then exits 3.
- The redirect URI is fixed at `http://127.0.0.1:8080/callback` in `oauth.py`; it must match the one registered on the Spotify app, and port 8080 must be free.
- `oauth.py` and `spotify_auth.py` each keep their own copy of the scope list. Change both together.
- In `oauth.py` the values in `.env` win over the environment. In `mix.py` it is the other way round: a variable already set in the environment wins over `.env`.
- The access token in `.env` has no recorded expiry, so the client treats a 401 as stale and retries once with a fresh token from the refresh token.
- A fresh access token is written back to the repository's own `.env`, even when `--env-file` names another file.
