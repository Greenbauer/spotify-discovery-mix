#!/usr/bin/env python3
"""Skip-logger health for the web-player now-playing bar.

`state/watcher_alive` is a keep-alive touch file. It can stay fresh while
`state/nowplaying.jsonl` is frozen on one title. This script is the health
signal: content recency plus whether the same title|artists run has lasted
too long.

Does not call Spotify.

`--live` checks the live skip watcher (live_watch.py) instead: its
`live_watcher_alive` touch file must be fresh, and `live_watcher.json` must not
report an auth failure. Exit 1 with needs_restart means start it again
(scripts/install_live_watcher.sh --ensure); needs_user_ping means the Spotify
token was refused and only a new refresh token fixes it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE = Path(os.environ.get("MIX_STATE_DIR") or (ROOT / "state"))
DEFAULT_STALE_HOURS = 6.0
DEFAULT_FROZEN_HOURS = 2.0
DEFAULT_ALIVE_FRESH_HOURS = 1.0
# The live watcher touches its file after every poll and at least once a
# minute while it waits (including a long 429 or auth back-off).
DEFAULT_LIVE_STALE_MINUTES = 20.0


def parse_ts(raw: Any) -> datetime | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc)


def _hours(delta_s: float | None) -> float | None:
    if delta_s is None:
        return None
    return round(delta_s / 3600.0, 4)


def _track_key(row: dict) -> str:
    title = str(row.get("title") or row.get("name") or "")
    artists = row.get("artists") or row.get("artist") or ""
    if isinstance(artists, list):
        artists = ", ".join(str(a) for a in artists if a)
    else:
        artists = str(artists)
    return f"{title}|{artists}"


def read_nowplaying(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def alive_mtime(path: Path) -> datetime | None:
    if not path.is_file():
        return None
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def assess_health(
    *,
    records: list[dict],
    now: datetime,
    alive_mtime_at: datetime | None = None,
    stale_hours: float = DEFAULT_STALE_HOURS,
    frozen_hours: float = DEFAULT_FROZEN_HOURS,
    alive_fresh_hours: float = DEFAULT_ALIVE_FRESH_HOURS,
) -> dict[str, Any]:
    """Return one health object. No I/O. `now` must be timezone-aware."""
    last = records[-1] if records else None
    last_ts = parse_ts(last.get("ts") if last else None)
    last_title = str(last.get("title") or last.get("name") or "") if last else None
    last_artists_raw = last.get("artists") if last else None
    if isinstance(last_artists_raw, list):
        last_artists: str | None = ", ".join(str(a) for a in last_artists_raw if a)
    elif last is None:
        last_artists = None
    else:
        last_artists = str(last_artists_raw or last.get("artist") or "") or None

    frozen_start = last_ts
    if last is not None:
        key = _track_key(last)
        for row in reversed(records):
            if _track_key(row) != key:
                break
            row_ts = parse_ts(row.get("ts"))
            if row_ts is not None:
                frozen_start = row_ts

    content_age_s = (now - last_ts).total_seconds() if last_ts is not None else None
    frozen_age_s = (
        (now - frozen_start).total_seconds() if frozen_start is not None else None
    )
    alive_age_s = (
        (now - alive_mtime_at).total_seconds() if alive_mtime_at is not None else None
    )

    stale_content = (not records) or last_ts is None or (
        content_age_s is not None and content_age_s >= stale_hours * 3600
    )
    frozen_bar = frozen_age_s is not None and frozen_age_s >= frozen_hours * 3600
    alive_fresh = alive_age_s is not None and 0 <= alive_age_s < alive_fresh_hours * 3600
    keep_alive_mask = bool(alive_fresh and (stale_content or frozen_bar))
    ok = not stale_content and not frozen_bar
    needs_user_ping = not ok

    parts: list[str] = []
    if not records:
        parts.append("no nowplaying.jsonl lines")
    elif last_ts is None:
        parts.append("last nowplaying line has no parseable ts")
    if stale_content and records and last_ts is not None:
        parts.append(
            f"stale content ({_hours(content_age_s)}h >= {stale_hours:g}h)"
        )
    if frozen_bar:
        title = last_title or ""
        artists = last_artists or ""
        parts.append(
            f"frozen bar ({_hours(frozen_age_s)}h of {title}|{artists} "
            f">= {frozen_hours:g}h)"
        )
    if keep_alive_mask:
        parts.append(
            f"keep-alive mask (watcher_alive {_hours(alive_age_s)}h old, "
            f"fresh < {alive_fresh_hours:g}h)"
        )
    if ok:
        reason = "ok"
    else:
        reason = "; ".join(parts) if parts else "unhealthy"

    return {
        "ok": ok,
        "needs_user_ping": needs_user_ping,
        "stale_content": stale_content,
        "frozen_bar": frozen_bar,
        "keep_alive_mask": keep_alive_mask,
        "ages": {
            "content_hours": _hours(content_age_s),
            "frozen_hours": _hours(frozen_age_s),
            "alive_hours": _hours(alive_age_s),
        },
        "last_title": last_title,
        "last_artists": last_artists,
        "last_ts": last.get("ts") if last else None,
        "reason": reason,
    }


def health_from_state(
    state_dir: Path,
    *,
    now: datetime | None = None,
    stale_hours: float = DEFAULT_STALE_HOURS,
    frozen_hours: float = DEFAULT_FROZEN_HOURS,
    alive_fresh_hours: float = DEFAULT_ALIVE_FRESH_HOURS,
) -> dict[str, Any]:
    when = now or datetime.now(timezone.utc)
    return assess_health(
        records=read_nowplaying(state_dir / "nowplaying.jsonl"),
        now=when,
        alive_mtime_at=alive_mtime(state_dir / "watcher_alive"),
        stale_hours=stale_hours,
        frozen_hours=frozen_hours,
        alive_fresh_hours=alive_fresh_hours,
    )


def assess_live(
    *,
    health: dict | None,
    alive_mtime_at: datetime | None,
    now: datetime,
    stale_minutes: float = DEFAULT_LIVE_STALE_MINUTES,
) -> dict[str, Any]:
    """Live watcher health. No I/O. `now` must be timezone-aware."""
    age_s = (now - alive_mtime_at).total_seconds() if alive_mtime_at else None
    alive = age_s is not None and age_s < stale_minutes * 60
    auth_failed = bool((health or {}).get("auth_failed"))
    if not alive:
        reason = "live watcher not running (no fresh live_watcher_alive)"
    elif auth_failed:
        reason = "Spotify refused the token (AUTH_FAILED)"
    else:
        reason = "ok"
    return {
        "ok": alive and not auth_failed,
        "needs_restart": not alive,
        "needs_user_ping": alive and auth_failed,
        "alive_minutes": None if age_s is None else round(age_s / 60, 2),
        "counts": (health or {}).get("counts"),
        "last_event": (health or {}).get("last_event"),
        "reason": reason,
    }


def live_from_state(state_dir: Path, *, now: datetime | None = None) -> dict[str, Any]:
    path = state_dir / "live_watcher.json"
    try:
        health = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    except (OSError, json.JSONDecodeError):
        health = None
    return assess_live(
        health=health,
        alive_mtime_at=alive_mtime(state_dir / "live_watcher_alive"),
        now=now or datetime.now(timezone.utc),
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Print skip-logger health JSON. watcher_alive alone is not health."
        )
    )
    p.add_argument(
        "--state-dir",
        default=str(DEFAULT_STATE),
        help="directory with nowplaying.jsonl and watcher_alive",
    )
    p.add_argument(
        "--stale-hours",
        type=float,
        default=DEFAULT_STALE_HOURS,
        help="content is stale if no lines or last ts older than this (default 6)",
    )
    p.add_argument(
        "--frozen-hours",
        type=float,
        default=DEFAULT_FROZEN_HOURS,
        help="frozen if the same title|artists has run this long (default 2)",
    )
    p.add_argument(
        "--alive-fresh-hours",
        type=float,
        default=DEFAULT_ALIVE_FRESH_HOURS,
        help="watcher_alive is fresh if mtime is newer than this (default 1)",
    )
    p.add_argument(
        "--live",
        action="store_true",
        help="check the live skip watcher (live_watch.py) instead of the web-player log",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.live:
        report = live_from_state(Path(args.state_dir))
        print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
        return 0 if report["ok"] else 1
    report = health_from_state(
        Path(args.state_dir),
        stale_hours=args.stale_hours,
        frozen_hours=args.frozen_hours,
        alive_fresh_hours=args.alive_fresh_hours,
    )
    print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
