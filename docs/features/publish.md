# Publish the mix

`mix.py publish` puts the saved mix on your private "Discovery Mix" playlist: it reuses the playlist it made before, or creates one, and replaces its tracks. `--dry-run` prints the track URIs and stops before any Spotify playlist call.

## Surfaces

- command: `publish`
- option: `--dry-run`
- option: `--force`
- source: `mix.py`

## Reach

Run `.venv/bin/python mix.py publish` after `build_mix`. With no saved mix it runs `build_mix` first. The playlist name comes from `MIX_PLAYLIST_NAME` (default `Discovery Mix`), and its id is kept in `state/config.json`.

## Verify

- `mix.py::a rate-limited publish never creates a duplicate Discovery Mix`
- `mix.py::a created playlist is recorded before a rate-limited fill (no second orphan)`
- `mix.py::a 429 on the stored-playlist lookup raises`

The `mix.py::` anchors are check messages inside `mix.py self_test`, which runs with no network.

1. Make a new empty folder `D` and write `D/last_mix.json` holding `{"tracks":[{"id":"T1","uri":"spotify:track:T1"}]}`. Run `.venv/bin/python mix.py --env-file D/none.env --state-dir D publish --dry-run`: it prints `publish 1 tracks → playlist 'Discovery Mix'`, then `dry-run: not calling Spotify playlist CRUD`, then `spotify:track:T1`, and exits 0.
2. Run `.venv/bin/python mix.py publish --help`: it lists `--dry-run` and `--force`.

re-walk: none -- a command-line tool with no browser page; a real publish writes to your Spotify playlist

## Gotchas

- `--dry-run` is only safe when a saved mix exists. With no `last_mix.json` it runs `build_mix` first, and that calls Spotify.
- Publish refuses to replace the playlist with fewer than 60% of the tracks it last published, unless you pass `--force`.
- A 429 on the lookup of the stored playlist raises instead of creating a second Discovery Mix. A playlist it creates is saved to `state/config.json` before it is filled, so a rate-limited fill does not leave an orphan.
- If the stored playlist is gone or owned by someone else, publish creates a new one and the old id is dropped.
