# Live skip watcher

`live_watch.py` runs all the time and polls Spotify's currently-playing endpoint, so it sees what you play on any device. When a Discovery Mix track ends it judges it: skipped if it stopped before 30 seconds (or before half of a song under a minute), else heard. A skip leaves the playlist at once and a new discovery takes its place, usually within a minute; a hear leaves after `MIX_ROLL_DELAY_MIN`.

## Surfaces

- script: `live_watch.py`
- script: `scripts/install_live_watcher.sh`
- script: `scripts/watcher_health.py`
- option: `--live`
- option: `--ensure`
- option: `--uninstall`
- option: `--supervise`
- option: `--state-dir`
- option: `--env-file`
- source: `live_watch.py`
- source: `scripts/install_live_watcher.sh`
- source: `scripts/watcher_health.py`
- source: `state_lock.py`
- source: `rate_limit.py`

## Reach

Run `scripts/install_live_watcher.sh` once on the mixer box: it installs a systemd user service, or a nohup supervisor where systemd is missing. The hourly routine runs `scripts/install_live_watcher.sh --ensure`, which restarts the watcher only if it died. `scripts/watcher_health.py --live` prints its health, and `--uninstall` stops and removes it. The `LIVE_*` settings in `.env.example` change the skip thresholds and the poll pace.

## Verify

- `tests/test_live_watch.py::test_early_stop_is_a_skip`
- `tests/test_live_watch.py::test_short_song_uses_half_its_length`
- `tests/test_live_watch.py::test_skip_is_logged_and_rolls_at_once`
- `tests/test_live_watch.py::test_heard_is_logged_but_roll_waits`
- `tests/test_live_watch.py::test_skips_are_throttled_to_one_roll_a_minute`
- `tests/test_live_watch.py::test_paused_mix_track_keeps_fast_polling`
- `tests/test_live_watch.py::test_skips_down_weight_an_artist`
- `tests/test_live_watch.py::test_missing_watcher_needs_restart`
- `tests/test_live_watch_limits.py::test_refused_refresh_token_is_an_auth_failure`
- `tests/test_live_watch_limits.py::test_long_429_waits_it_out_and_does_not_roll`

1. Run `.venv/bin/python live_watch.py --help`: it prints the usage with `--state-dir` and `--env-file` and exits without polling.
2. Make a new empty folder `D` and run `python3 scripts/watcher_health.py --live --state-dir D`: it prints JSON with `"needs_restart":true` and the reason `live watcher not running (no fresh live_watcher_alive)`, and exits 1.
3. Run `scripts/install_live_watcher.sh --help`: it prints `usage: scripts/install_live_watcher.sh [--ensure|--uninstall]` and exits 2 without installing anything.

re-walk: none -- a background process on the mixer box that polls your Spotify playback; no browser page

## Gotchas

- `scripts/install_live_watcher.sh` with no argument installs and starts the watcher. Only `--help` or any other unknown argument is a safe way to look at it.
- Pausing is not skipping. A track you skip in under about 5 seconds can slip past between polls and stays on the playlist.
- It polls every 5 seconds only while a mix track is playing. A paused mix track and other music are polled every 30 seconds, and nothing playing every 90. The test `test_paused_mix_track_keeps_fast_polling` checks the 30-second pace, despite its name.
- `--ensure` restarts only a dead watcher. A refused refresh token prints `AUTH_FAILED` and sets `needs_user_ping`; a restart cannot fix that, so `--ensure` exits 1 and leaves it for you.
- One watcher at a time: `state/live_watcher.lock` makes a second one exit. Do not also run `mix.py watch_plays`.
- `live_watch.py` and the scripts read `MIX_STATE_DIR`; `mix.py` does not, so pass `--state-dir` to `mix.py` when the state lives elsewhere.
- The systemd path of the installer was not exercised when it shipped (#11); only the nohup path was tested, in a Linux container.
