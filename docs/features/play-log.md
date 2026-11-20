# Log plays from Spotify

`mix.py log_plays` records the Discovery Mix tracks you played in `state/played.json`, from Spotify's recently-played list and (without `--recent-only`) what is playing now. `mix.py watch_plays` is the older polling loop that does the same from currently-playing only. Heard tracks then roll off the playlist and stay out of later mixes.

## Surfaces

- command: `log_plays`
- command: `watch_plays`
- option: `--recent-only`
- option: `--interval`
- option: `--idle-interval`
- option: `--other-interval`
- source: `mix.py`
- source: `state_lock.py`

## Reach

After the first `publish`, run `.venv/bin/python mix.py log_plays --recent-only` as a step of the hourly routine. `watch_plays` takes `--interval` (default 12 s while the mix plays), `--other-interval` (60 s on other music) and `--idle-interval` (90 s when nothing plays).

## Verify

- `tests/test_live_watch.py::test_append_heard_keeps_outcome_and_dedupes`
- `tests/test_live_watch.py::test_record_play_waits_for_the_plays_lock`
- `mix.py::_append_heard records a new play`
- `mix.py::heard title+artist excludes a remaster with a different track id`

The `mix.py::` anchors are check messages inside `mix.py self_test`, which runs with no network.

1. With `.venv` set up (see [setup](setup.md)), run `.venv/bin/python mix.py log_plays --help`: it lists `--recent-only`.
2. With `.venv` set up (see [setup](setup.md)), run `.venv/bin/python mix.py watch_plays --help`: it lists `--interval`, `--idle-interval` and `--other-interval` with defaults 12, 90 and 60.

re-walk: none -- a command-line tool with no browser page; logging plays reads your Spotify listening

## Gotchas

- Only plays of tracks on the current mix, or from the Discovery Mix playlist, are recorded. Recently-played is never a taste seed.
- `--recent-only` makes one cheap request but misses most skips: Spotify usually leaves out plays under about 30 seconds.
- Do not run `watch_plays` next to the live skip watcher (`live_watch.py`): `watch_plays` logs a track as heard the moment it starts, so it never sees a skip. The live watcher is the one poller now.
- `played.json` writers share `state/plays.lock` (`state_lock.py`), so the watcher and the hourly routine cannot overwrite each other's rows.
- Both commands stop with `no playlist_id in state/config.json` until a mix has been published.
