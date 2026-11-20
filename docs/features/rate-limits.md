# Spotify rate limits

When Spotify answers 429 with a long `Retry-After`, or with Dev Mode's `QUOTA_EXCEEDED`, `build_mix`, `publish`, `roll_playlist` and `maybe_refresh` print `RATE_LIMITED ...` and exit 75 instead of reading the refusal as "no results". The play-logging commands and the live watcher handle a 429 differently (see Reach). A refused rebuild or top-up records a cooldown in `state/rate_limit.json`, and later runs skip that work until it ends. Searches are cached so repeat runs search only for new artists.

## Surfaces

- source: `rate_limit.py`
- source: `http_client.py`
- source: `search_cache.py`
- source: `mix.py`

## Reach

Nothing to run; this is how the commands behave:

- `build_mix`, `publish`, `roll_playlist` and `maybe_refresh` exit 75 with `RATE_LIMITED ...` on a refused playlist or library read, playlist write, search, related-artists or top-tracks call. A `roll_playlist` whose top-up search is refused still removes tracks and exits 0.
- `probe` exits 75 only when `GET /me` is refused. A 429 on one of the endpoints it probes is printed as `False`, the same as an endpoint that is gone.
- `log_plays` and `watch_plays` read a 429 as nothing played: recently-played returns an empty list and currently-playing returns nothing, so they log no plays and exit or keep polling as usual.
- The live watcher (`live_watch.py`) logs the 429, records a `player` cooldown and keeps running, polling again when it ends.
- `ingest_ui`, `self_test` and `print_auth_url` make no Spotify call.

`MIX_SEARCH_CACHE_DAYS` (default 7) sets how long a search result is reused from `state/search_cache.json`.

## Verify

- `tests/test_rate_limits.py::test_every_lookup_raises_on_429`
- `tests/test_rate_limits.py::test_other_errors_still_read_as_no_results`
- `tests/test_rate_limits.py::test_rate_limited_command_exits_75`
- `tests/test_rate_limits.py::test_no_retry_after_backs_off_6h_doubling_to_48h`
- `tests/test_rate_limits.py::test_clear_resets_the_doubling`
- `tests/test_rate_limits.py::test_a_429_is_not_cached`
- `tests/test_live_watch_limits.py::test_quota_429_without_retry_after_backs_off_hours_and_persists`
- `mix.py::Retry-After HTTP-date parses instead of crashing`
- `mix.py::a 429 with no cached copy is not treated as empty`

The `mix.py::` anchors are check messages inside `mix.py self_test`, which runs with no network.

1. With `.venv` set up (see [setup](setup.md)), make a new empty folder `D` and write `D/rate_limit.json` holding `{"search":{"until":"2099-01-01T00:00:00+00:00","reason":"test","hits":1}}`. Run `.venv/bin/python mix.py --env-file D/none.env --state-dir D maybe_refresh`: it prints `RATE_LIMITED rebuild deferred: cooldown until 2099-01-01T00:00:00+00:00 (test, hit 1x)` and exits 75 with no Spotify call.
2. With `.venv` set up (see [setup](setup.md)), run `.venv/bin/python -m unittest discover tests`: every test passes and none needs Spotify.

re-walk: none -- a command-line tool with no browser page; a real 429 needs Spotify to refuse your account

## Gotchas

- A cooldown lasts for `Retry-After` when Spotify sends one, else 6 hours, doubling on each repeat up to 48 hours. A successful run clears it, which resets the doubling.
- There are three scopes: `search` (builds and roll top-ups), `player` (the live watcher's polls) and `roll` (rolls the live watcher starts). The cooldowns survive a restart.
- A short `Retry-After` (60 seconds or less) is waited out instead. Spotify sends it as seconds or as an HTTP date; the date form used to crash the parser.
- Before #13 a search 429 read as "no results", so every hourly rebuild failed with an empty pool and burned more quota. Other 4xx answers still read as no results.
- Your playlists are cached by `snapshot_id` in `state/playlist_cache.json`. A 429 on a changed playlist uses the cached copy; with no copy it raises rather than read the playlist as empty.
