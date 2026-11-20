# Feature map

One file per thing you can do with Discovery Mix: what it owns in code, how you reach it, what proves it works, and what tends to go wrong. Read the files of the features a change touches before making it. The `feature-map` line in `.vibe-verifier` fails a pull request that adds a `mix.py` command, an option or an entry-point script no feature lists, lists one that no longer exists, or leaves a source glob or a test anchor dangling. The format is the Vibe Verifier catalog's `docs/feature-map.md`.

Every Verify step here is safe to run: none calls Spotify or starts a sign-in, and none touches your real `state/`. Nothing is walkable in a browser, so every feature says `re-walk: none`.

| Feature | Commands, scripts and options |
|---|---|
| [Set up and run the commands](setup.md) | `scripts/ensure_venv.sh`, `--state-dir`, `--env-file` |
| [Sign in to Spotify once](sign-in.md) | `oauth.py`, `print_auth_url`, `--redirect-uri` |
| [Build a mix](build-mix.md) | `build_mix`, `--force` |
| [Publish the mix](publish.md) | `publish`, `--dry-run`, `--force` |
| [Roll the playlist](roll-playlist.md) | `roll_playlist` (alias `roll`) |
| [Refresh a used-up mix](maybe-refresh.md) | `maybe_refresh` |
| [Log plays from Spotify](play-log.md) | `log_plays`, `watch_plays`, `--recent-only`, `--interval`, `--idle-interval`, `--other-interval` |
| [Live skip watcher](live-watcher.md) | `live_watch.py`, `scripts/install_live_watcher.sh`, `scripts/watcher_health.py --live`, `--ensure`, `--uninstall` |
| [Web-player now-playing log](web-player-log.md) | `ingest_ui`, `scripts/nowplaying_server.py`, `scripts/nowplaying_watcher.py`, `scripts/watcher_health.py` |
| [Probe the Spotify endpoints](probe.md) | `probe` |
| [Self-test](self-test.md) | `self_test` |
| [Spotify rate limits](rate-limits.md) | none: how every command behaves on a 429 |
