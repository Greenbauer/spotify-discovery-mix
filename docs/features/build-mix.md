# Build a mix

`mix.py build_mix` works out about 40 popular tracks that are new to you and saves them to `state/last_mix.json`. It seeds taste from playlists you created (and, optionally, the artists in Liked Songs), finds similar artists through ListenBrainz and Spotify, and picks their popular tracks you have not heard or saved. It prints the mix and does not change any Spotify playlist.

## Surfaces

- command: `build_mix`
- option: `--force`
- source: `mix.py`
- source: `pool.py`
- source: `brainz.py`
- source: `search_cache.py`
- source: `http_client.py`
- source: `docs/ALGORITHM.md`
- source: `.env.example`

## Reach

Run `.venv/bin/python mix.py build_mix`. It needs the Spotify tokens in `.env` (see the sign-in feature). `--force` saves the new mix even when it is much smaller than the one it replaces. The `MIX_*` settings in `.env.example` change its size, popularity floor, tracks per artist and seeds; `docs/ALGORITHM.md` explains each rule.

## Verify

- `tests/test_pool.py::test_used_up_top_artists_do_not_empty_the_pool`
- `tests/test_pool.py::test_fresh_library_stops_once_the_pool_is_full`
- `tests/test_pool.py::test_songs_below_the_popularity_floor_do_not_count`
- `tests/test_rate_limits.py::test_repeat_searches_hit_the_cache_across_runs`
- `mix.py::persist_mix refuses a materially smaller mix`
- `mix.py::Path C guesses stay below min_popularity`
- `mix.py::resolve_track rejects The National Forest for The National`
- `mix.py::build skips a song you own under a different release id`

The `mix.py::` anchors are check messages inside `mix.py self_test`, which runs with no network.

1. With `.venv` set up (see [setup](setup.md)), run `.venv/bin/python mix.py build_mix --help`: it lists `--force` and says it overwrites `last_mix.json` even with a much smaller mix.
2. With `.venv` set up (see [setup](setup.md)), run `.venv/bin/python mix.py self_test`: the last line reads `self_test failures: 0`. Never run `build_mix` itself as a check, because it calls Spotify with your account.

re-walk: none -- a command-line tool with no browser page; a real build reads your Spotify account

## Gotchas

- A build refuses to overwrite `last_mix.json` with a mix under 60% of the previous one (`MIX_MIN_REPLACE_RATIO`), so a rate-limited build cannot wipe a good mix. `--force` turns that off.
- Every track in every playlist you created is excluded from the output, even playlists skipped as seeds (holiday, baby). Liked Songs and the play log are excluded too. The one exception is the Discovery Mix playlist itself: it is skipped entirely, as neither seed nor exclude, so an unheard track from an earlier mix may come back.
- The pick is week-stable: two builds in the same ISO week pick the same tracks from the same pool. `maybe_refresh` gets around this by excluding the tracks of the mix it replaces.
- Spotify's Dev Mode removed the popularity field and artist top-tracks, so most picks come from search rank ("Path C"). A search guess always scores below `MIX_MIN_POPULARITY` (55 by default), so a measured popularity at that floor outranks every guess.
- The pool keeps searching similar artists until enough candidates survive every filter. Counting raw search hits instead emptied the pool once the first artists' songs were all heard (fixed in #12, pinned by `tests/test_pool.py`).
- `mix.py` is about 3,700 lines. Recent changes moved helpers out (`brainz.py`, `http_client.py`, `spotify_auth.py`) rather than grow it, and `mix.py` re-exports their names.
