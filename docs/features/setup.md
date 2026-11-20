# Set up and run the commands

`scripts/ensure_venv.sh` makes sure the repository's `.venv` exists and can import `requests`, recreating it from `requirements.txt` when it cannot. `mix.py` is the mixer's command line: every command takes `--state-dir` (default `state/`) and `--env-file` (default `.env`) before the command name. Settings live in `.env`, copied from `.env.example`.

## Surfaces

- script: `scripts/ensure_venv.sh`
- option: `--state-dir`
- option: `--env-file`
- source: `scripts/ensure_venv.sh`
- source: `requirements.txt`
- source: `.env.example`
- source: `mix.py`
- source: `state/.gitkeep`
- source: `.gitignore`

## Reach

Copy `.env.example` to `.env`, then run `./scripts/ensure_venv.sh` before any mix command, and run the commands with `.venv/bin/python mix.py <command>`. `.venv/bin/python mix.py --help` lists every command.

## Verify

No test covers setup.

1. With `.venv` set up by `./scripts/ensure_venv.sh`, run `.venv/bin/python mix.py --help`: it lists `--state-dir`, `--env-file` and the commands `build_mix`, `publish`, `log_plays`, `ingest_ui`, `roll_playlist` (alias `roll`), `maybe_refresh`, `watch_plays`, `probe`, `self_test` and `print_auth_url`, and exits 0 without reading `.env`.
2. With `.venv` in place and able to import `requests`, run `./scripts/ensure_venv.sh`: it prints `ensure_venv: .venv ok (...)` and exits 0 without changing anything.

re-walk: none -- a command-line tool with no browser page

## Gotchas

- Without `.venv`, falling through to the system `python3` usually means no `requests`, and `mix.py` fails on import. In the hourly routine that is a quiet failure (skip ingest and publish stop working), so run `ensure_venv.sh` first.
- Options go before the command: `mix.py --state-dir D publish`, not `mix.py publish --state-dir D`.
- `mix.py` ignores `MIX_STATE_DIR`; `live_watch.py`, `scripts/watcher_health.py`, the now-playing servers and the installer read it.
- A variable already set in the environment wins over the same key in `.env`.
- `state/` holds your play log, playlist id and caches. Its JSON files are gitignored; never commit `.env`, play logs, playlist ids or listening history.
