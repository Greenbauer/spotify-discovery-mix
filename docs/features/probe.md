# Probe the Spotify endpoints

`mix.py probe` prints your Spotify user and whether related-artists, recommendations, artist top-tracks and the popularity field still work for your app. Spotify removed these for new and Dev Mode apps in November 2024 and February 2026.

## Surfaces

- command: `probe`
- source: `mix.py`

## Reach

Run `.venv/bin/python mix.py probe`. It needs the Spotify tokens in `.env`.

## Verify

1. Run `.venv/bin/python mix.py probe --help`: it prints `usage: mix.py probe [-h]` and exits 0 without calling Spotify. Never run `probe` itself as a check, because it calls Spotify with your account.

re-walk: none -- a command-line tool with no browser page; a real probe calls Spotify with your account

## Gotchas

- It only prints. Nothing is saved: the mixer checks the same endpoints on every run and turns each one off after its first 4xx.
- No test covers it; the README's API notes (August 2026) are the reference for what each answer means.
