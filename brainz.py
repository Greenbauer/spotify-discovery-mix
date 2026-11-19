"""MusicBrainz + ListenBrainz clients: similar artists with no API key.

Spotify's related-artists is 403 for new apps, so these replace it. Moved out
of mix.py unchanged.
"""

from __future__ import annotations

from http_client import Http

MB_API = "https://musicbrainz.org/ws/2"
LB_SIMILAR = "https://labs.api.listenbrainz.org/similar-artists/json"
LB_SIMILAR_ALGO = "session_based_days_9000_session_300_contribution_5_threshold_15_limit_50_skip_30"


class MusicBrainz:
    def __init__(self) -> None:
        self.http = Http(min_interval=1.05)  # MusicBrainz asks for ~1 req/s

    def artist_mbid(self, name: str) -> str | None:
        resp = self.http.request(
            "GET",
            f"{MB_API}/artist/",
            params={"query": f'artist:"{name}"', "fmt": "json", "limit": 1},
        )
        if resp.status_code >= 400:
            return None
        artists = (resp.json() or {}).get("artists") or []
        if not artists:
            return None
        return artists[0].get("id")


class ListenBrainz:
    def __init__(self) -> None:
        self.http = Http(min_interval=0.15)

    def similar_artists(self, mbid: str, limit: int = 12) -> list[tuple[str, float]]:
        resp = self.http.request("GET", LB_SIMILAR, params={"artist_mbids": mbid, "algorithm": LB_SIMILAR_ALGO})
        if resp.status_code >= 400:
            return []
        try:
            payload = resp.json()
        except Exception:
            return []
        out: list[tuple[str, float]] = []
        seen: set[str] = set()
        for row in _rows(payload):
            name = (
                row.get("artist_credit_name")
                or row.get("artist_name")
                or row.get("name")
                or ""
            ).strip()
            other = (row.get("artist_mbid") or "").lower()
            if not name or other == mbid.lower() or name.lower() in seen:
                continue
            seen.add(name.lower())
            out.append((name, _score(row)))
        out.sort(key=lambda x: x[1], reverse=True)
        return out[:limit]


def _rows(payload: object) -> list[dict]:
    """Flatten ListenBrainz's list-of-lists (or list of dicts) into rows."""
    rows: list[dict] = []
    if isinstance(payload, list):
        for block in payload:
            if isinstance(block, list):
                rows.extend(x for x in block if isinstance(x, dict))
            elif isinstance(block, dict):
                rows.append(block)
    return rows


def _score(row: dict) -> float:
    try:
        return float(row.get("score") or 0)
    except (TypeError, ValueError):
        return 0.0
