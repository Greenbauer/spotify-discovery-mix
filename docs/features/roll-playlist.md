# Roll the playlist

`mix.py roll_playlist` (alias `roll`) keeps the live playlist at about `MIX_SIZE` tracks: it removes tracks you heard at least `MIX_ROLL_DELAY_MIN` minutes ago, removes skipped tracks and songs you already own at once, and appends new discoveries at the bottom.

## Surfaces

- command: `roll_playlist`
- source: `mix.py`
- source: `state_lock.py`

## Reach

Run `.venv/bin/python mix.py roll_playlist` (or `roll`) after the first `publish`. It is a step of the hourly routine, and the live skip watcher runs it after a skip. It prints `ROLL noop` when there is nothing to do, else `ROLL removed=N kept=K added=A size=S`.

## Verify

- `tests/test_live_watch.py::test_skipped_row_rolls_off_without_the_delay`
- `tests/test_rate_limits.py::test_cooldown_skips_the_top_up_search`
- `mix.py::kept tracks stay at the top; new tracks append`
- `mix.py::a track heard under a different release id still rolls off`
- `mix.py::tracks already in your library leave the mix, by id or by title`
- `mix.py::a noop roll does not touch rolled_at (the idle clock keeps running)`

The `mix.py::` anchors are check messages inside `mix.py self_test`, which runs with no network.

1. Make a new empty folder `D` and run `.venv/bin/python mix.py --env-file D/none.env --state-dir D roll_playlist`: it prints `no playlist_id in state/config.json. Publish first.` and exits 1 before any Spotify call.
2. Run `.venv/bin/python mix.py roll --help` and `.venv/bin/python mix.py roll_playlist --help`: both print the `roll_playlist` usage.

re-walk: none -- a command-line tool with no browser page; a real roll reads and writes your Spotify playlist

## Gotchas

- Heard means the track id or its title and artist is in the play log, because Spotify often logs a play under a different release id than the playlist holds.
- A roll does not use the 60% floor that `build_mix` and `publish` use: a one-track top-up is the normal write.
- During a search cooldown (`state/rate_limit.json`) a roll still removes heard and skipped tracks but skips the top-up.
- The live watcher and the hourly routine both roll. `state_lock.py` holds `state/playlist.lock` so they never write the playlist at the same time. The locks are not re-entrant, so never nest two steps that take the same lock.
- A noop roll leaves `rolled_at` alone, so the idle clock that `maybe_refresh` reads keeps running.
