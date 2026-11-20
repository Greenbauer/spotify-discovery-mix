# Refresh a used-up mix

`mix.py maybe_refresh` builds and publishes a whole new mix when the current one is used up: every track heard, at least 90% heard, published `MIX_MAX_AGE_DAYS` (7) days ago, or unchanged for `MIX_IDLE_DAYS` (3) days. With no mix at all it builds the first one. Otherwise it prints `mix still open` and does nothing.

## Surfaces

- command: `maybe_refresh`
- source: `mix.py`
- source: `rate_limit.py`

## Reach

Run `.venv/bin/python mix.py maybe_refresh`. It is the last step of the hourly routine, so a separate Monday `publish` is optional. On a rebuild it prints `MIX_FINISHED (<reason>)` and then `NEW_MIX <count>`.

## Verify

- `tests/test_rate_limits.py::test_cooldown_skips_the_rebuild_with_no_api_call`
- `tests/test_rate_limits.py::test_rate_limited_build_records_a_cooldown`
- `tests/test_rate_limits.py::test_successful_rebuild_clears_the_cooldown`
- `mix.py::the Oct 8 mix (0/40 heard, 11d unchanged) is finished`
- `mix.py::the replacement build excludes every track of the stale mix`
- `mix.py::a failed publish restores last_mix (no unpublished build left behind)`
- `mix.py::a failed first publish leaves no last_mix, so the next hour bootstraps again`

The `mix.py::` anchors are check messages inside `mix.py self_test`, which runs with no network.

1. With `.venv` set up (see [setup](setup.md)), make a new empty folder `D` and write `D/last_mix.json` holding one track and a `published_at` of the current UTC time, for example `{"tracks":[{"id":"T1","uri":"spotify:track:T1"}],"published_at":"<now in ISO 8601>"}`. Run `.venv/bin/python mix.py --env-file D/none.env --state-dir D maybe_refresh`: it prints `mix progress: 0/1 heard, 1 remaining` and `mix still open`, and exits 0 with no Spotify call.

re-walk: none -- a command-line tool with no browser page; a real refresh builds from and writes to your Spotify account

## Gotchas

- Idle counts from the latest of `published_at`, `rolled_at` and `generated_at`. Rolling only moves on hears, so before the idle rule an unheard mix sat unchanged for 11 days (October 2026).
- The new build excludes every track of the mix it replaces. The pick is week-stable, so without that a same-week rebuild would publish the same songs again.
- If the build or the publish fails, the old `last_mix.json` is put back (or removed when there was none), so the next hourly run retries instead of seeing an open mix.
- During a search cooldown, and only when a rebuild is due (the mix is used up, or there is none), it prints `RATE_LIMITED rebuild deferred: ...` and exits 75 with no Spotify call and no `MIX_FINISHED` line. A mix that is still open prints `mix still open` and exits 0 first, cooldown or not.
- It holds the same `state/playlist.lock` as `roll_playlist`.
