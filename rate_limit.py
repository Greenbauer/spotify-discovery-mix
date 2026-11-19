"""Persisted Spotify rate-limit cooldowns (state/rate_limit.json).

When Spotify answers 429 and the wait is too long to sit out, the command
records a cooldown here instead of retrying every hour. Until it ends, the
callers skip the work that would hit Spotify again:

  scope "search"  set by a build or roll top-up whose search / related /
                  top-tracks call was refused. maybe_refresh skips the rebuild
                  and roll_playlist removes tracks without topping up, with no
                  API calls for the skipped part.
  scope "player"  set by live_watch.py when currently-playing is refused.
  scope "roll"    set by live_watch.py when a roll it triggers is refused (a
                  playlist read or write); the watcher runs no roll until
                  it ends, even after a restart.

Length: Retry-After when Spotify sends a usable one. Without it (Dev Mode
QUOTA_EXCEEDED often has none), 6 h, doubling on each repeat up to 48 h. A
successful run clears its scope, which resets the doubling.

CRUD: written on a 429, read before the work, removed by clear() on success.
The file holds at most one small record per scope.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

FILE = "rate_limit.json"
DEFAULT_BACKOFF_S = 6 * 3600
MAX_BACKOFF_S = 48 * 3600


def _read(state: Path) -> dict[str, Any]:
    try:
        data = json.loads((state / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(state: Path, data: dict[str, Any]) -> None:
    path = state / FILE
    if not data:
        path.unlink(missing_ok=True)
        return
    state.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _parse(raw: Any) -> datetime | None:
    try:
        when = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def record(
    state: Path,
    scope: str,
    retry_after: float | None,
    reason: str | None = None,
    now: datetime | None = None,
) -> datetime:
    """Start (or extend) a cooldown for `scope`. Returns when it ends."""
    now = now or datetime.now(timezone.utc)
    data = _read(state)
    prev = data.get(scope) or {}
    backoff = int(prev.get("backoff_s") or 0)
    if retry_after is not None:
        wait = float(retry_after)
    else:
        backoff = min(backoff * 2, MAX_BACKOFF_S) if backoff else DEFAULT_BACKOFF_S
        wait = float(backoff)
    until = now + timedelta(seconds=wait)
    data[scope] = {
        "until": until.isoformat(),
        "backoff_s": backoff,
        "reason": reason or "rate limited",
        "hits": int(prev.get("hits") or 0) + 1,
        "last_hit": now.isoformat(),
    }
    _write(state, data)
    return until


def active(state: Path, scope: str, now: datetime | None = None) -> dict[str, Any] | None:
    """The cooldown record for `scope` if it has not ended yet, else None."""
    rec = _read(state).get(scope)
    if not isinstance(rec, dict):
        return None
    until = _parse(rec.get("until"))
    if until is None or until <= (now or datetime.now(timezone.utc)):
        return None
    return rec


def clear(state: Path, scope: str) -> None:
    data = _read(state)
    if data.pop(scope, None) is not None:
        _write(state, data)


def describe(rec: dict[str, Any]) -> str:
    return f"cooldown until {rec.get('until')} ({rec.get('reason')}, hit {rec.get('hits')}x)"
