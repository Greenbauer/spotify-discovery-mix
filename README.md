# Discovery Mix

A ~40-track **novel + popular** Discovery Mix for a personal Spotify account (Grok Bot / local agent).
`mix.py` never starts OAuth by itself; `oauth.py` is the one-time, opt-in helper that does
(see [Setup](#what-we-still-need-from-you)). Registering the Spotify app is still on you.

Business-logic decisions (seeds, excludes, Path B/C, failure modes) are in
[docs/ALGORITHM.md](docs/ALGORITHM.md). Spotify-first: no Last.fm. Read that
before changing taste.

```
./scripts/ensure_venv.sh              # recreate .venv if missing/broken (import requests)
.venv/bin/python mix.py self_test     # local filters, no network
.venv/bin/python mix.py build_mix     # compute 40 tracks (needs tokens)
.venv/bin/python mix.py publish       # create/replace "Discovery Mix"
.venv/bin/python mix.py publish --dry-run
.venv/bin/python mix.py log_plays     # record plays of OUR playlist only
.venv/bin/python mix.py probe         # which Spotify endpoints still work
.venv/bin/python mix.py ingest_ui     # mark mix tracks from a now-playing JSONL
.venv/bin/python mix.py roll_playlist # drop delayed hears + songs you already own; append discoveries (~40)
.venv/bin/python mix.py maybe_refresh # if the mix is heard, 7d old, or 3d unchanged, publish a new one
.venv/bin/python mix.py watch_plays   # older poller; logs heard on start, no skips (use live_watch.py)
.venv/bin/python live_watch.py        # live skip watcher; install with scripts/install_live_watcher.sh
python3 scripts/watcher_health.py     # skip-logger health JSON (not watcher_alive)
```

Run `./scripts/ensure_venv.sh` before mix commands. If `.venv` is gone, falling
through to system `python3` quietly drops `requests` and skip ingest/publish
degrade. `state/watcher_alive` is a keep-alive touch file only: it can stay
fresh while `state/nowplaying.jsonl` is frozen on one title. Use
`scripts/watcher_health.py` (stale content, frozen bar, keep-alive mask). Skip
detection is now the live watcher (see "Live skip detection"); the web-player
bar log is a secondary source. Do not add another currently-playing poll.

`build_mix` and `publish` take `--force` to overwrite a mix much smaller than the one it
replaces. Without it they refuse, so a rate-limited build cannot destroy a good mix.

## API reality (August 2026)

Two Spotify lock-downs stacked:

### 1. 27 Nov 2024 — discovery endpoints killed for new apps

[Official post](https://developer.spotify.com/blog/2024-11-27-changes-to-the-web-api).
New apps and Dev Mode apps without extended quota get **403** on:

| Endpoint | Status for a new app |
|---|---|
| `GET /v1/recommendations` | dead |
| `GET /v1/artists/{id}/related-artists` | dead |
| `GET /v1/audio-features`, `/audio-analysis` | dead |
| Featured / category playlists, 30s previews in multi-get | dead |

Grandfathered **extended quota** apps that already used these still have them.
Individuals generally cannot apply for extended quota anymore (org + 250k MAU bar since 2025).

### 2. Feb / Mar 2026 — Dev Mode surface shrinks further

[Changelog](https://developer.spotify.com/documentation/web-api/references/changes/february-2026)
and [migration guide](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide).
**Extended quota apps are unchanged.** Dev Mode apps (what a personal mixer will be):

Still works (and this script uses):

- `GET /me`, `GET /me/playlists`, `POST /me/playlists`, `PUT /playlists/{id}`
- Playlist items: `GET/PUT/POST/DELETE /playlists/{id}/items` (**`/tracks` renamed**)
- Liked songs: `GET /me/tracks`
- Recently played: `GET /me/player/recently-played` (log_plays only)
- Search: `GET /search` (**max limit 10**)
- `GET /artists/{id}`, `GET /artists/{id}/albums`, `GET /albums/{id}/tracks`, `GET /tracks/{id}`
- `GET /me/top/{type}` — **available, but this mixer NEVER calls it**

Removed or stripped in Dev Mode:

- `GET /artists/{id}/top-tracks` — **removed**
- Batch `GET /tracks?ids=`, `GET /artists?ids=` — **removed** (fetch one-by-one)
- `POST /users/{id}/playlists`, `GET /users/{id}/playlists` — use `/me/playlists`
- Track/artist **`popularity` field removed**
- Browse new-releases / categories

Dev Mode also: app owner must have **Premium**, **5 users** per app. Client IDs per
developer raised to 25 in July 2026.

`mix.py probe` reports which of related-artists / recommendations / top-tracks /
popularity still work for *your* token. It only prints: the mixer feature-detects the
same endpoints per run and disables them after the first 4xx, so there is nothing to persist.

## Discovery method (no deprecated recs endpoint)

```
playlists you CREATED  (+ optional Liked Songs as artist seeds)
        │
        ├─ exclude: seasonal (wrong month), baby/kids/nursery, "Discovery Mix"
        ├─ those tracks → EXCLUDE set
        └─ those artists → SEED set
                │
                ▼
     similar artists, in order:
       1. MusicBrainz name → MBID
          + ListenBrainz labs similar-artists (no key)
       2. Spotify related-artists             (only if probe says it still works)
                │
                ▼
     those artists' popular tracks:
       1. Spotify /artists/{id}/top-tracks            (extended quota only)
       2. Spotify search artist:"Name" type=track     (Dev Mode happy path;
          search rank is a soft score, not a flat 55)
                │
                ▼
     drop if in created playlists, likes, or state/played.json
     drop sleep/ambient/rain-mill titles; primary Spotify artist must match
     keep measured Spotify pop >= 55; Path C guesses stay below that and stay distinct
     cap 2 tracks / artist, ~40 tracks, week-stable RNG
```

## Quality

Filters added after a live mix came back as 40 Path C tracks, all popularity 55.
Discovery is Spotify + ListenBrainz. Last.fm is not used.

- **Primary-artist resolve.** `The National Forest` is not `The National`. Featured
  guests are ignored when matching.
- **Junk titles/artists.** Sleep, ambient mills, white noise, rain-on-roof,
  thunder-sounds, spa/massage/yoga/meditation, 432 Hz, lofi study. Standalone
  hit titles like `Thunder` stay.
- **Primary-only seeds.** Remix-credit names do not expand similar-artists.
  `MIX_MIN_SEED_COUNT` (default 2) drops one-off primaries.
- **Short names refused.** Length `< 3` (e.g. `Py`) and blocked words are not
  seeded or searched.
- **Path C ranking.** Search hits get distinct scores from their rank (never
  a flat 55). Real Spotify popularity, when present, sorts above guesses.
  `MIX_MAX_PATH_C` caps guesses only when measured tracks are also in the pool.

**Never seeded from:** `GET /me/top`, recently-played, baby/house listening,
out-of-season holiday playlists, Spotify's own editorial lists.

**Excluded from output regardless:** every track in every playlist you created — including
the ones skipped for seeding — plus Liked Songs and the play log. Skipping a playlist as a
taste source never makes its tracks eligible to be recommended back to you. The only total
skip is Discovery Mix itself, so an unheard track
from last week can still return.

Season from **playlist name** (skipped as seeds unless the current month matches):

| Name matches | In-season |
|---|---|
| Christmas / Xmas / holiday | December |
| Halloween | October |
| Thanksgiving | 15–30 November |
| 4th of July | 25 Jun – 10 Jul |
| Valentine | February |

## Env vars

Copy `.env.example` to `.env` (gitignored).

| Variable | Required | Purpose |
|---|---|---|
| `SPOTIFY_CLIENT_ID` | yes (for live run) | Dashboard app |
| `SPOTIFY_CLIENT_SECRET` | yes | Dashboard secret |
| `SPOTIFY_REFRESH_TOKEN` | yes | Headless token; script refreshes access |
| `SPOTIFY_ACCESS_TOKEN` | no | Skip refresh if still valid |
| `MIX_PLAYLIST_NAME` | no | default `Discovery Mix` |
| `MIX_SIZE` | no | default `40` |
| `MIX_MIN_POPULARITY` | no | default `55` |
| `MIX_MAX_PER_ARTIST` | no | default `2` |
| `MIX_USE_LIKES` | no | default `1`. Likes are ALWAYS excluded from output; this only controls whether their artists also seed. |
| `MIX_MIN_SEED_COUNT` | no | default `2`. Primary artist must appear this many times before seeding. |
| `MIX_MAX_PATH_C` | no | default `10`. Max Path C guesses when measured Spotify-pop tracks exist. Ignored for a guess-only mix. |
| `MIX_ROLL_DELAY_MIN` | no | default `5`. Minutes a heard mix track stays on the playlist before `roll_playlist` removes it. |
| `LIVE_SKIP_SECONDS` | no | default `30`. Live watcher: a mix track that stops before this is a skip. |
| `LIVE_SKIP_RATIO` | no | default `0.5`. Live watcher: ...or before this share of its length, when that is shorter. |
| `LIVE_POLL_SECONDS` | no | default `5`. Live watcher: seconds between polls while the mix plays. |
| `MIX_SEARCH_CACHE_DAYS` | no | default `7`. Days a Spotify search result is reused from `state/search_cache.json`. |
| `LIVE_ROLL_GAP_SECONDS` | no | default `60`. Live watcher: minimum seconds between rolls it triggers. |
| `MIX_IDLE_DAYS` | no | default `3`. `maybe_refresh` rebuilds a mix whose playlist has not changed (no publish, no roll that wrote) for this many days, even at 0 heard. |
| `MIX_MAX_AGE_DAYS` | no | default `7`. `maybe_refresh` rebuilds a mix published this many days ago, even while it rolls. |

## Local state (`state/`)

| File | Written by | Contents |
|---|---|---|
| `config.json` | `publish`, `roll_playlist` | mix playlist id + uri + track_count |
| `last_mix.json` | `build_mix`, `roll_playlist` | the current playlist tracks + week stamp |
| `played.json` | `log_plays`, `live_watch.py` | track ids played *from our playlist URI*; live rows add `outcome` (`skipped` / `heard`) |
| `live_watcher.json` | `live_watch.py` | live watcher health: counts, last event, `auth_failed` |
| `live_watcher_alive` | `live_watch.py` | touched after every poll; `watcher_health.py --live` reads it |
| `live_watcher.lock` | `live_watch.py` | single-instance lock |
| `rate_limit.json` | builds, rolls, `live_watch.py` | Spotify 429 cooldowns by scope (`search`, `player`, `roll`); deleted when the next call succeeds |
| `search_cache.json` | `build_mix`, `roll_playlist` | Spotify search results (trimmed) for `MIX_SEARCH_CACHE_DAYS`; expired entries dropped on save |
| `plays.lock`, `playlist.lock` | `state_lock.py` | serialize `played.json` writes and playlist rolls between the watcher and the hourly routine |
| `live_watcher.log` | `install_live_watcher.sh` | watcher output on the nohup path (systemd uses the journal) |
| `similar_cache.json` | `build_mix` | ListenBrainz similar-artist cache (14d) |
| `playlist_cache.json` | `build_mix`, `roll_playlist` | your playlists' tracks by `snapshot_id`; unchanged playlists are not re-read, and a 429 falls back to this copy. Rewritten each library read, so deleted playlists drop out |
| `nowplaying.jsonl` | `scripts/nowplaying_*.py` | web-player now-playing log, read by `ingest_ui` |
| `watcher_alive` | skip-logger keep-alive | mtime only; **not** health. Use `scripts/watcher_health.py` |
| `watch_plays.pid` | `watch_plays` | pid of the running watcher |

JSON under `state/` is gitignored except `.gitkeep`.

## What we still need from you

1. **Spotify developer app** at https://developer.spotify.com/dashboard
   (you own it; Premium required for Dev Mode). One redirect URI e.g.
   `http://127.0.0.1:8080/callback`.
2. **OAuth once.** Easiest: `.venv/bin/python oauth.py` — it serves the callback on
   `http://127.0.0.1:8080/callback`, exchanges the code, and writes `SPOTIFY_REFRESH_TOKEN`
   into `.env` with mode 600. It prints the URL to `/tmp/spotify-auth-url.txt`.

   To do it by hand instead, these are the scopes:

   `playlist-read-private playlist-read-collaborative user-library-read playlist-modify-private playlist-modify-public user-read-recently-played user-read-currently-playing user-read-playback-state user-read-private`

   Print the URL (does not open a browser or start a server):

   ```
   .venv/bin/python mix.py print_auth_url --redirect-uri http://127.0.0.1:8080/callback
   ```

   Exchange the `code` yourself:

   ```
   curl -u "$SPOTIFY_CLIENT_ID:$SPOTIFY_CLIENT_SECRET" -d grant_type=authorization_code \
     -d code=THE_CODE -d redirect_uri=http://127.0.0.1:8080/callback \
     https://accounts.spotify.com/api/token
   ```

   Put `refresh_token` in `.env` as `SPOTIFY_REFRESH_TOKEN`.
3. After first `publish`, run the hourly play-log / skip-watcher so heard mix
   tracks drop off and stay out of the next pool:

   `ensure_venv` → `install_live_watcher.sh --ensure` → `watcher_health` → `ingest_ui` → `log_plays --recent-only` → `roll_playlist` → `maybe_refresh`

   `install_live_watcher.sh --ensure` restarts the live skip watcher if it
   died (see "Live skip detection"). `watcher_health` is the web-player
   skip-logger check (`nowplaying.jsonl` recency and a frozen title+artists
   run). `watcher_alive` alone is not that check.

   `maybe_refresh` is the full rebuild when the mix is empty, mostly heard,
   `MIX_MAX_AGE_DAYS` (7) old, or idle for `MIX_IDLE_DAYS` (3). Idle means
   no publish and no roll changed the playlist, which is what an unlistened
   mix looks like: rolling only moves on hears. The rebuild never republishes
   the tracks it replaces. A separate Monday `publish` cron is optional now.

   A command that Spotify rate-limits (429 with a long `Retry-After`, or Dev
   Mode's `QUOTA_EXCEEDED`) prints `RATE_LIMITED ...` and exits `75`. That
   covers playlist and library reads, every playlist write, and search,
   related-artists and top-tracks: a refused search is never read as "no
   results". A refused rebuild or roll top-up records a cooldown in
   `state/rate_limit.json`: `Retry-After` when Spotify sends one, otherwise 6 h,
   doubling on each repeat up to 48 h. Until it ends, `maybe_refresh` prints
   `RATE_LIMITED rebuild deferred: cooldown until ...` and exits 75 with no API
   call (and no `MIX_FINISHED`), and `roll_playlist` still removes heard and
   skipped tracks but skips the top-up. A successful run clears it. Searches
   are cached for `MIX_SEARCH_CACHE_DAYS` (7) in `state/search_cache.json`, so
   repeat builds and rolls only search for new artists.

Similar artists use MusicBrainz + ListenBrainz (no key). Last.fm is not used.

## Rolling playlist

When detection marks a mix track as heard, `roll_playlist` waits
`MIX_ROLL_DELAY_MIN` minutes (default 5), then removes it. Remaining songs stay
at the top in the same relative order. New discovery tracks (same Mixer
pipeline as `build_mix`, including Path C / junk / primary-only seeds) append
at the bottom so the playlist stays about `MIX_SIZE` (40).

Heard means the track id **or its title+artist** is in the play log: Spotify often
logs a play under a different release id than the playlist holds. A song that is
already in one of your playlists or Liked Songs is removed too, with no delay.

A track heard less recently than the delay stays put. If nothing is eligible
to remove and the playlist is already about `MIX_SIZE`, the command prints
`ROLL noop` and exits 0. It also prints `ROLL noop` without writing when the
playlist is short but no new discoveries were found. Otherwise it prints
`ROLL removed=N kept=K added=A size=S` and writes the playlist with one
`replace_playlist_tracks` (`/playlists/{id}/items`, fallback `/tracks`).

`roll_playlist` does not ping anyone and does not poll currently-playing.

## Live skip detection

`live_watch.py` runs all the time on the mixer box and polls Spotify's
currently-playing endpoint, so it sees what you play on any device. When a
Discovery Mix track ends it decides:

- **Skipped**: it stopped before 30 seconds (or before half the song, for a
  song under a minute). It leaves the playlist at once and a new discovery
  takes its place, usually within a minute. Each skip also halves that
  artist's chance of being picked again.
- **Heard**: anything longer. It leaves after the usual `MIX_ROLL_DELAY_MIN`.

Pausing is not skipping. A track you skip in under about 5 seconds can slip
past between polls and stays on the playlist (longer right after other music
or silence, when polls are 30 to 90 s apart). It polls every 5 s only while
the mix is playing; when Spotify rate-limits it, it stops polling until the
cooldown in `state/rate_limit.json` ends, even across a restart. It stays quiet except for
`AUTH_FAILED` when Spotify refuses the token. Thresholds are the `LIVE_*`
env vars above; details in `docs/ALGORITHM.md`.

Install on the box (systemd user service if available, otherwise a nohup
supervisor):

```
scripts/install_live_watcher.sh              # install and start
scripts/install_live_watcher.sh --ensure     # hourly: restart only if dead
scripts/watcher_health.py --live             # health JSON, exit 1 if unhealthy
scripts/install_live_watcher.sh --uninstall  # stop and remove
```

Do not also run `mix.py watch_plays`: it logs a track as heard the moment it
starts. Tests: `.venv/bin/python -m unittest discover tests`.

## Layout

```
mix.py            the mixer CLI
live_watch.py     always-on skip watcher (currently-playing, rolls on skips)
http_client.py    HTTP retry / Retry-After helpers (moved out of mix.py)
state_lock.py     flock locks on state/ shared by the watcher and hourly commands
rate_limit.py     persisted Spotify 429 cooldowns (state/rate_limit.json)
search_cache.py   Spotify search cache (state/search_cache.json)
brainz.py         MusicBrainz + ListenBrainz similar-artist clients (moved out of mix.py)
spotify_auth.py   scopes, authorize URL, token refresh (moved out of mix.py)
tests/            unittest suites (live watcher, pool, rate limits)
oauth.py          one-time OAuth helper (writes .env, mode 600)
docs/ALGORITHM.md business logic (seeds, excludes, Path B/C, rolling)
docs/features/    feature map: one file per command or feature, kept true by the feature-map gate
pool.py           candidate gathering for builds (search until enough survive the filters)
requirements.txt .env.example
scripts/          skip-logger helpers (nowplaying, ensure_venv, watcher_health, install_live_watcher)
state/            local only (gitignored JSON)
.vibe-verifier    gates every pull request runs (check `Gates`, .github/workflows/vibe-verifier.yml)
```

Do not commit `.env`, play logs, playlist ids, or listening history.
