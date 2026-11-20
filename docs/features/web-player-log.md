# Web-player now-playing log

A small local server takes now-playing events from the Spotify web player (`open.spotify.com`) and appends one JSON line per new title to `state/nowplaying.jsonl`. `mix.py ingest_ui` marks the mix tracks in that log as heard, with no Web API call. `scripts/watcher_health.py` reports whether the log is still moving. This is the older, secondary skip source; the live skip watcher is the main one.

## Surfaces

- command: `ingest_ui`
- script: `scripts/nowplaying_server.py`
- script: `scripts/nowplaying_watcher.py`
- script: `scripts/watcher_health.py`
- option: `--stale-hours`
- option: `--frozen-hours`
- option: `--alive-fresh-hours`
- option: `--state-dir`
- source: `scripts/nowplaying_server.py`
- source: `scripts/nowplaying_watcher.py`
- source: `scripts/watcher_health.py`
- source: `mix.py`

## Reach

Run one of `scripts/nowplaying_server.py` or `scripts/nowplaying_watcher.py`; each listens on `127.0.0.1:8765` for a JSON POST with `title` and `artists` from a browser watcher of the web player. `nowplaying_server.py` takes it only on `/event` and also needs `ts`; `nowplaying_watcher.py` stamps the time itself and answers the browser's CORS check. The hourly routine then runs `python3 scripts/watcher_health.py` and `.venv/bin/python mix.py ingest_ui`.

## Verify

- `mix.py::watcher_health.py loads`

The `mix.py::` anchor is a check message inside `mix.py self_test`, which runs with no network.

1. Make a new empty folder `D`. Write `D/last_mix.json` holding `{"tracks":[{"id":"T1","uri":"spotify:track:T1","name":"Song One","artists":["Band A"]}]}` and `D/nowplaying.jsonl` holding the one line `{"ts":"2026-11-20T10:00:00Z","title":"Song One","artists":"Band A"}`. Run `.venv/bin/python mix.py --env-file D/none.env --state-dir D ingest_ui`: it prints `heard (web player): Song One` and `new mix plays recorded: 1`, and `D/played.json` gains a row with `"source": "web-player-ui"`.
2. Make a new empty folder `D` and write `D/nowplaying.jsonl` holding one line with a `ts` more than 6 hours old. Run `python3 scripts/watcher_health.py --state-dir D`: it prints JSON with `"ok":false` and `"stale_content":true`, and exits 1.

re-walk: none -- the browser side is a watcher of the Spotify web player, which needs your signed-in Spotify session

## Gotchas

- `state/watcher_alive` is a keep-alive touch file, not health. It can stay fresh while `nowplaying.jsonl` is frozen on one title. `watcher_health.py` calls that a keep-alive mask and reports it as unhealthy.
- Do not add another currently-playing poll to make up for a stale or frozen log. Reload the web player instead.
- Both server scripts bind `127.0.0.1:8765`, so only one can run at a time. Both write to `state/` next to the repository, or to `MIX_STATE_DIR` when it is set; a hard-coded path once meant `ingest_ui` never saw what the server wrote.
- `ingest_ui` matches by title and artist, never title alone, so two songs that share a name ("Home", "Stay") are not both marked heard.
