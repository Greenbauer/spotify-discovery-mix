"""Shared fixtures for the live watcher tests (not a test module)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import live_watch as lw  # noqa: E402
import mix  # noqa: E402

MIX_URI = "spotify:playlist:MIX"
S = lw.Settings()


def body(tid="A", progress_s=0.0, duration_s=200.0, ctx=MIX_URI, playing=True, kind="track"):
    return {
        "is_playing": playing,
        "progress_ms": int(progress_s * 1000),
        "context": {"uri": ctx} if ctx else None,
        "item": {
            "id": tid,
            "type": kind,
            "uri": f"spotify:track:{tid}",
            "name": f"Song {tid}",
            "duration_ms": int(duration_s * 1000),
            "artists": [{"name": f"Artist {tid}", "id": f"ar{tid}"}],
        },
    }


def snap(*args, mix_ids=frozenset(), **kwargs):
    return lw.parse_snapshot(body(*args, **kwargs), MIX_URI, set(mix_ids))


class FakeResp:
    def __init__(self, code, payload=None, headers=None):
        self.status_code = code
        self._payload = payload
        self.headers = headers or {}
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self):
        if self._payload is None:
            raise ValueError("no body")
        return self._payload


class FakeSpotify:
    def __init__(self, responses):
        self.responses = list(responses)

    def _request(self, method, path, params=None):
        assert (method, path) == ("GET", lw.PLAYER_PATH)
        nxt = self.responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


class WatcherBase(unittest.TestCase):
    """A Watcher on a temp state dir with a two-track mix; no tests of its own."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        state = Path(self.tmp.name)
        self.paths = mix.Paths(root=state, state=state)
        mix.write_json(self.paths.config, {"playlist_id": "MIX", "playlist_uri": MIX_URI})
        mix.write_json(self.paths.last_mix, {"tracks": [{"id": "A"}, {"id": "B"}]})

    def tearDown(self):
        self.tmp.cleanup()

    def watcher(self, responses):
        return lw.Watcher(self.paths, FakeSpotify(responses), S)

