"""Spotify search results cached in state/search_cache.json.

A build searches tens of artists, and a roll after every skip runs a small
build, so the same searches repeat all day. Caching them (TTL 7 days,
MIX_SEARCH_CACHE_DAYS) cuts Spotify search volume to the new queries only.
Only answered searches are cached, empty ones included; a 429 raises before
anything is stored. Entries are trimmed to the fields the mixer reads.

CRUD: get_or_fetch() adds an entry on a miss, entries are never updated in
place (a stale one is refetched), and save() drops expired entries.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

DEFAULT_TTL_DAYS = 7.0


class SearchCache:
    def __init__(self, path: Path | None, ttl_days: float = DEFAULT_TTL_DAYS) -> None:
        """path None = in memory only (a Mixer with no state dir, as in tests)."""
        self.path = path
        self.ttl_s = ttl_days * 86400
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path else {}
        except (OSError, ValueError):
            data = {}
        self.entries: dict[str, Any] = data if isinstance(data, dict) else {}
        self.hits = 0
        self.misses = 0

    def _fresh(self, entry: Any, now: float) -> bool:
        return isinstance(entry, dict) and now - float(entry.get("ts") or 0) < self.ttl_s

    def get_or_fetch(self, key: str, fetch: Callable[[], Any]) -> Any:
        now = time.time()
        entry = self.entries.get(key)
        if self._fresh(entry, now):
            self.hits += 1
            return entry["v"]
        self.misses += 1
        value = fetch()
        self.entries[key] = {"ts": int(now), "v": value}
        return value

    def save(self) -> None:
        now = time.time()
        self.entries = {k: e for k, e in self.entries.items() if self._fresh(e, now)}
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.entries, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(self.path)
