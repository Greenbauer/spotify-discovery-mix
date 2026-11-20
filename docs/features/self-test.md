# Self-test

`mix.py self_test` runs about 170 built-in checks with no network and no Spotify account: holiday and baby playlist skips, junk titles, artist matching, mix selection, rolling, refresh, rate limits and the playlist cache. It prints `ok` or `FAIL` per check and exits 1 if any check fails.

## Surfaces

- command: `self_test`
- source: `mix.py`

## Reach

Run `.venv/bin/python mix.py self_test`. The unit tests are separate: `.venv/bin/python -m unittest discover tests`.

## Verify

- `mix.py::Christmas skipped in August`
- `mix.py::baby playlist skipped`
- `mix.py::standalone Thunder (real hit) is kept`
- `mix.py::select_mix_tracks respects size`

1. Run `.venv/bin/python mix.py self_test`: no line says `FAIL`, and the last line reads `self_test failures: 0`, with exit code 0. A few other lines (the library summary of a fake account, two `ROLL` lines) are printed by the code under test.

re-walk: none -- a command-line check with no browser page

## Gotchas

- The checks live inside `mix.py` (`cmd_self_test`), not under `tests/`. They use fake clients and temporary folders, so they never touch `state/` or Spotify.
- Some checks swap `load_client` for a fake and put it back in a `finally`. A new check that skips the `finally` would leave the fake in place for every later check.
- Its dates are fixed (2026-08-30 and others), so the season checks do not depend on today's date.
