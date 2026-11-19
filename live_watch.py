#!/usr/bin/env python3
"""Live skip watcher for Discovery Mix.

An always-on loop that polls GET /me/player/currently-playing every few
seconds, on whatever device you listen on. When the track changes it judges
the track that just ended:

  SKIPPED  it stopped before LIVE_SKIP_SECONDS (default 30 s), or before
           LIVE_SKIP_RATIO (default 0.5) of its length when that is shorter
           (songs under a minute). Spotify's own "a play counts" mark is about
           30 s, so this matches what recently-played would have missed.
  HEARD    anything longer.

Only plays from the Discovery Mix playlist, or of a track on the current mix,
count. A pause is not a skip: a paused track stays pending, and if nothing
plays for IDLE_FLUSH_S it is logged only when it was already heard.

Each judged play goes into state/played.json with "outcome". A skip triggers
roll_playlist right away (at most once every LIVE_ROLL_GAP_SECONDS), so the
track is replaced within about a minute. A heard track keeps the
MIX_ROLL_DELAY_MIN delay before the roll that removes it.

Polls every 5 s only while the mix plays (30 s on other music or paused,
90 s idle). A 429 records a cooldown in state/rate_limit.json (Retry-After,
else 6 h doubling) and nothing polls until it ends, even after a restart.

Health: touches state/live_watcher_alive every loop and writes
state/live_watcher.json. `scripts/watcher_health.py --live` reads both.
Quiet by design: it prints AUTH_FAILED (and flags it in the health file) and
otherwise only logs. A track skipped faster than one poll is never seen.

Linux box install: scripts/install_live_watcher.sh. Supersedes `mix.py
watch_plays`, which logs a track as heard the moment it starts; do not run both.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

import mix
import rate_limit
from state_lock import state_lock

PLAYER_PATH = "/me/player/currently-playing"
POLL_OTHER_S = 30.0
POLL_IDLE_S = 90.0
IDLE_FLUSH_S = 600.0
ROLL_RETRY_S = 120.0
HEARD_ROLL_MARGIN_S = 15.0
AUTH_RETRY_S = 900.0
ERROR_RETRY_S = 60.0
# Health is touched at least this often, even inside a long 429 back-off, so
# a waiting watcher never looks dead to `watcher_health.py --live`.
HEALTH_TOUCH_S = 60.0


def _env_float(name: str, default: float) -> float:
    raw = mix.env(name)
    return default if raw is None else float(raw)


@dataclass
class Settings:
    skip_seconds: float = 30.0
    skip_ratio: float = 0.5
    poll_mix_s: float = 5.0
    roll_gap_s: float = 60.0
    heard_delay_s: float = 300.0

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            skip_seconds=_env_float("LIVE_SKIP_SECONDS", 30.0),
            skip_ratio=_env_float("LIVE_SKIP_RATIO", 0.5),
            poll_mix_s=_env_float("LIVE_POLL_SECONDS", 5.0),
            roll_gap_s=_env_float("LIVE_ROLL_GAP_SECONDS", 60.0),
            heard_delay_s=60.0 * mix.env_int("MIX_ROLL_DELAY_MIN", 5),
        )


def classify(progress_ms: int, duration_ms: int, settings: Settings) -> str:
    """"skipped" if the play stopped before the skip threshold, else "heard"."""
    threshold = settings.skip_seconds * 1000
    if duration_ms > 0:
        threshold = min(threshold, settings.skip_ratio * duration_ms)
    return "skipped" if progress_ms < threshold else "heard"


@dataclass
class Playing:
    track_id: str
    uri: str
    name: str
    artists: list[str]
    duration_ms: int
    progress_ms: int
    from_mix: bool
    is_playing: bool = True


@dataclass
class Finished:
    play: Playing
    outcome: str


def parse_snapshot(body: Any, mix_uri: str, mix_ids: set[str]) -> Playing | None:
    """One currently-playing response to a Playing, or None (nothing / not a track)."""
    if not isinstance(body, dict):
        return None
    item = body.get("item") or {}
    tid = item.get("id")
    if not tid or item.get("type", "track") != "track":
        return None
    ctx_uri = (body.get("context") or {}).get("uri") or ""
    return Playing(
        track_id=tid,
        uri=item.get("uri") or f"spotify:track:{tid}",
        name=item.get("name") or "",
        artists=mix.artist_names(item),
        duration_ms=int(item.get("duration_ms") or 0),
        progress_ms=int(body.get("progress_ms") or 0),
        from_mix=ctx_uri == mix_uri or tid in mix_ids,
        is_playing=bool(body.get("is_playing")),
    )


@dataclass
class Tracker:
    """Turns a stream of snapshots into judged plays, one per track change."""

    settings: Settings
    current: Playing | None = None

    def observe(self, snap: Playing | None) -> Finished | None:
        if snap is None:
            return None
        cur = self.current
        if cur is not None and snap.track_id == cur.track_id:
            # Same track: keep the furthest point reached (a seek back or a
            # repeat does not undo a listen).
            cur.progress_ms = max(cur.progress_ms, snap.progress_ms)
            cur.duration_ms = snap.duration_ms or cur.duration_ms
            cur.from_mix = cur.from_mix or snap.from_mix
            cur.is_playing = snap.is_playing
            return None
        self.current = snap
        return self._judge(cur)

    def flush_idle(self) -> Finished | None:
        """Nothing has played for a while: log the pending track only if heard."""
        done = self._judge(self.current)
        self.current = None
        if done is not None and done.outcome == "heard":
            return done
        return None

    def _judge(self, play: Playing | None) -> Finished | None:
        if play is None or not play.from_mix:
            return None
        return Finished(play, classify(play.progress_ms, play.duration_ms, self.settings))


@dataclass
class RollScheduler:
    """When to run roll_playlist: now for a skip, after the delay for a hear."""

    settings: Settings
    pending: list[float] = field(default_factory=list)
    last_run: float = float("-inf")

    def add(self, outcome: str, now: float) -> None:
        wait = 0.0
        if outcome != "skipped":
            wait = self.settings.heard_delay_s + HEARD_ROLL_MARGIN_S
        self.pending.append(now + wait)

    def next_at(self) -> float | None:
        if not self.pending:
            return None
        return max(min(self.pending), self.last_run + self.settings.roll_gap_s)

    def due(self, now: float) -> bool:
        at = self.next_at()
        return at is not None and now >= at

    def ran(self, now: float, ok: bool, retry_s: float = ROLL_RETRY_S) -> None:
        self.last_run = now
        if ok:
            self.pending = [t for t in self.pending if t > now]
        else:
            self.pending = [now + retry_s] + [t for t in self.pending if t > now]


def record_play(paths: mix.Paths, done: Finished, when: datetime) -> bool:
    """Append one judged play to played.json. False if the track is already there."""
    with state_lock(paths.state, "plays"):
        return _record_play_unlocked(paths, done, when)


def _record_play_unlocked(paths: mix.Paths, done: Finished, when: datetime) -> bool:
    played = mix.read_json(paths.played, {"plays": []})
    play = done.play
    added = mix._append_heard(
        played,
        track_id=play.track_id,
        uri=play.uri,
        name=play.name,
        played_at=when.isoformat(),
        source="live-watch",
        artists=play.artists,
        outcome=done.outcome,
    )
    if added:
        played["updated_at"] = when.isoformat()
        mix.write_json(paths.played, played)
    return added


def is_auth_error(exc: Exception) -> bool:
    """refresh_access_token's 4xx: the client or refresh token was refused.

    Its 5xx, and Http's "failed after retries", are outages, not auth.
    """
    return str(exc).startswith("token refresh -> 4")


def fetch_player(sp: mix.Spotify) -> tuple[str, Any]:
    """("ok", body|None) | ("limited", SpotifyRateLimited) | ("auth", msg) | ("error", msg)."""
    try:
        # Spotify._request retries once on 401 with a refreshed token.
        resp = sp._request("GET", PLAYER_PATH, params={"additional_types": "track"})
    except requests.RequestException as exc:
        return "error", str(exc)
    except RuntimeError as exc:
        return ("auth" if is_auth_error(exc) else "error"), str(exc)
    code = resp.status_code
    if code in {202, 204}:
        return "ok", None
    if code == 200:
        try:
            return "ok", resp.json()
        except ValueError:
            return "ok", None
    if code == 429:
        return "limited", mix.limit_error(resp, "currently-playing")
    if code == 401:
        return "auth", f"currently-playing -> 401: {resp.text[:200]}"
    return "error", f"currently-playing -> {code}"


class Watcher:
    def __init__(self, paths: mix.Paths, sp: mix.Spotify, settings: Settings) -> None:
        self.paths = paths
        self.sp = sp
        self.settings = settings
        self.tracker = Tracker(settings)
        self.rolls = RollScheduler(settings)
        self.last_active = time.monotonic()
        self.auth_failed = False
        # True at start so the first good poll clears any leftover (expired)
        # player cooldown and its doubling.
        self.limited = True
        self.health: dict[str, Any] = {
            "pid": os.getpid(),
            "started_at": _now().isoformat(),
            "counts": {"skipped": 0, "heard": 0, "rolls": 0, "roll_errors": 0},
        }

    def mix_context(self) -> tuple[str, set[str]]:
        config = mix.read_json(self.paths.config, {})
        pid = config.get("playlist_id") or ""
        uri = config.get("playlist_uri") or (f"spotify:playlist:{pid}" if pid else "")
        return uri, mix._mix_track_ids(self.paths)

    def step(self) -> float:
        """One poll + any due roll. Returns seconds to sleep."""
        status, value = fetch_player(self.sp)
        self.health["last_status"] = status
        # A back-off (auth, 429) returns before any roll: rolling would call
        # Spotify inside the window it asked us to stay out of.
        if status == "auth":
            return self._on_auth_failure(value)
        if status == "limited":
            return self._on_rate_limit(value)
        if status == "ok":
            self.auth_failed = False
            if self.limited:
                rate_limit.clear(self.paths.state, "player")
                self.limited = False
            sleep_for = self._on_snapshot(value)
        else:
            print(f"live_watch: {value}", flush=True)
            sleep_for = ERROR_RETRY_S
        self._maybe_roll()
        return self._cap_to_roll(sleep_for)

    def _on_snapshot(self, body: Any) -> float:
        now = time.monotonic()
        snap = parse_snapshot(body, *self.mix_context())
        done = self.tracker.observe(snap)
        if snap is not None and snap.is_playing:
            self.last_active = now
        elif now - self.last_active >= IDLE_FLUSH_S:
            done = done or self.tracker.flush_idle()
        if done is not None:
            self._log(done, now)
        if snap is not None and snap.is_playing:
            return self.settings.poll_mix_s if snap.from_mix else POLL_OTHER_S
        if self._mix_pending(now):
            # Paused on a mix track: the fast pace is only for actual mix
            # playback (quota), but stay off the 90 s idle pace so a resume
            # is seen within one 30 s poll.
            return POLL_OTHER_S
        if isinstance(body, dict) and body.get("is_playing"):
            return POLL_OTHER_S  # playing, but no track item (ad, private session)
        return POLL_IDLE_S

    def _mix_pending(self, now: float) -> bool:
        cur = self.tracker.current
        return bool(cur and cur.from_mix and now - self.last_active < IDLE_FLUSH_S)

    def _log(self, done: Finished, now: float) -> None:
        if not record_play(self.paths, done, _now()):
            return
        self.health["counts"][done.outcome] += 1
        self.health["last_event"] = {
            "outcome": done.outcome,
            "name": done.play.name,
            "progress_s": round(done.play.progress_ms / 1000, 1),
            "at": _now().isoformat(),
        }
        print(f"live_watch: {done.outcome} {done.play.name!r} "
              f"at {done.play.progress_ms // 1000}s", flush=True)
        self.rolls.add(done.outcome, now)

    def _on_auth_failure(self, msg: str) -> float:
        if not self.auth_failed:
            print(f"AUTH_FAILED live_watch: {msg}", flush=True)
        self.auth_failed = True
        return self._back_off(AUTH_RETRY_S)

    def _on_rate_limit(self, exc: Exception) -> float:
        """Persist the cooldown (Retry-After, else 6 h doubling) and sleep it out."""
        until = rate_limit.record(self.paths.state, "player", exc.retry_after, exc.reason)
        self.limited = True
        print(f"live_watch: {exc}; polling again at {until.isoformat()}", flush=True)
        return self._back_off(max((until - _now()).total_seconds(), self.settings.poll_mix_s))

    def startup_wait(self) -> float:
        """Seconds left on a currently-playing cooldown from before a restart."""
        cool = rate_limit.active(self.paths.state, "player")
        if not cool:
            return 0.0
        self.limited = True
        until = datetime.fromisoformat(cool["until"])
        print(f"live_watch: {rate_limit.describe(cool)}", flush=True)
        return self._back_off(max((until - _now()).total_seconds(), 0.0))

    def _back_off(self, seconds: float) -> float:
        until = _now().timestamp() + seconds
        self.health["backing_off_until"] = datetime.fromtimestamp(until, timezone.utc).isoformat()
        return seconds

    def _roll_blocked(self) -> bool:
        """A refused roll's cooldown (persisted, so it survives a restart)
        holds every roll, including ones new skips queue meanwhile."""
        return rate_limit.active(self.paths.state, "roll") is not None

    def _maybe_roll(self) -> None:
        now = time.monotonic()
        if not self.rolls.due(now) or self._roll_blocked():
            return
        ok, retry_s = run_roll(self.paths, self.sp)
        self.rolls.ran(now, ok, retry_s)
        self.health["counts"]["rolls" if ok else "roll_errors"] += 1

    def _cap_to_roll(self, sleep_for: float) -> float:
        at = self.rolls.next_at()
        if at is None or self._roll_blocked():
            return sleep_for
        return max(1.0, min(sleep_for, at - time.monotonic()))

    def nap(self, seconds: float) -> None:
        """Sleep, touching health at least every HEALTH_TOUCH_S."""
        end = time.monotonic() + seconds
        while (left := end - time.monotonic()) > 0:
            time.sleep(min(left, HEALTH_TOUCH_S))
            self.write_health()

    def write_health(self) -> None:
        self.health["updated_at"] = _now().isoformat()
        self.health["auth_failed"] = self.auth_failed
        mix.write_json(self.paths.state / "live_watcher.json", self.health)
        (self.paths.state / "live_watcher_alive").touch()


def run_roll(paths: mix.Paths, sp: mix.Spotify) -> tuple[bool, float]:
    """(ok, seconds before a retry). A rate-limited roll (a playlist read or
    write refused) waits out its cooldown, not ROLL_RETRY_S."""
    # cmd_roll_playlist holds the "playlist" lock, so it never overlaps the
    # hourly roll_playlist / maybe_refresh. A refused top-up search is handled
    # inside it (tracks still leave; the top-up waits for the cooldown).
    try:
        ok = mix.cmd_roll_playlist(paths, sp=sp) == 0
    except mix.SpotifyRateLimited as exc:
        until = rate_limit.record(paths.state, "roll", exc.retry_after, exc.reason)
        print(f"live_watch: roll rate limited: {exc}; retry at {until.isoformat()}", flush=True)
        return False, max((until - _now()).total_seconds(), ROLL_RETRY_S)
    except (Exception, SystemExit) as exc:  # noqa: BLE001 - keep the loop alive
        print(f"live_watch: roll failed: {exc}", flush=True)
        return False, ROLL_RETRY_S
    if ok:
        rate_limit.clear(paths.state, "roll")  # resets the doubling
    return ok, ROLL_RETRY_S


def _now() -> datetime:
    return datetime.now(timezone.utc)


@contextlib.contextmanager
def single_instance(state: Path):
    """Hold an exclusive lock so a supervisor and a service never both run."""
    state.mkdir(parents=True, exist_ok=True)
    with open(state / "live_watcher.lock", "w", encoding="utf-8") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("live_watch: another watcher holds the lock; exiting")
        fh.write(str(os.getpid()))
        fh.flush()
        yield


def connect(paths: mix.Paths) -> mix.Spotify:
    """load_client, retried. A refused refresh token is flagged, not crash-looped."""
    while True:
        try:
            return mix.load_client()
        except requests.RequestException as exc:
            print(f"live_watch: cannot reach Spotify: {exc}", flush=True)
            time.sleep(ERROR_RETRY_S)
        except RuntimeError as exc:
            if not is_auth_error(exc):
                print(f"live_watch: cannot reach Spotify: {exc}", flush=True)
                time.sleep(ERROR_RETRY_S)
                continue
            print(f"AUTH_FAILED live_watch: {exc}", flush=True)
            health = {"pid": os.getpid(), "auth_failed": True, "updated_at": _now().isoformat()}
            mix.write_json(paths.state / "live_watcher.json", health)
            (paths.state / "live_watcher_alive").touch()
            time.sleep(AUTH_RETRY_S)


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Live Discovery Mix skip watcher.")
    p.add_argument("--state-dir", default=os.environ.get("MIX_STATE_DIR") or str(mix.DEFAULT_STATE))
    p.add_argument("--env-file", default=str(mix.ROOT / ".env"))
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    mix.load_dotenv(Path(args.env_file))
    paths = mix.Paths(root=mix.ROOT, state=Path(args.state_dir))
    with single_instance(paths.state):
        watcher = Watcher(paths, connect(paths), Settings.from_env())
        print(f"live_watch: started pid={os.getpid()}", flush=True)
        watcher.write_health()
        watcher.nap(watcher.startup_wait())
        while True:
            sleep_for = watcher.step()
            watcher.write_health()
            watcher.nap(sleep_for)


if __name__ == "__main__":
    raise SystemExit(main())
