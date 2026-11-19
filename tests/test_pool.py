"""Candidate-pool regression tests. Run: .venv/bin/python -m unittest discover tests"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import mix  # noqa: E402
from pool import gather_until_usable  # noqa: E402


def _pl(tid: str, name: str, artist: str) -> dict:
    return {"id": tid, "uri": f"spotify:track:{tid}", "name": name,
            "artists": [{"name": artist, "id": f"id-{artist}"}]}


class _LibSp:
    caps = mix.SpotifyCaps()

    def created_playlists(self, uid):
        return [{"id": "p1", "name": "Deep Cuts"}]

    def playlist_items(self, pid):
        return [_pl("s1", "Seed One", "Seed Band"), _pl("s2", "Seed Two", "Seed Band")]

    def liked_tracks(self):
        return []


def _artist_tracks(artist: str, n: int = 8, low_pop: int = 0) -> list[mix.Candidate]:
    """n tracks; the first `low_pop` sit below the default popularity floor (55)."""
    return [
        mix.Candidate(f"{artist}-{i}", f"spotify:track:{artist}-{i}", f"{artist} song {i}",
                      [artist], [f"id-{artist}"], 40 if i < low_pop else 70, "s")
        for i in range(n)
    ]


class GatherTest(unittest.TestCase):
    def test_stops_once_enough_candidates_are_usable(self):
        fetched = []

        def fetch(a):
            fetched.append(a)
            return [a + "1", a + "2"]

        def keep(cands):
            return [c for c in cands if not c.startswith("A")]

        groups = gather_until_usable("ABCDE", fetch, keep, 3)
        self.assertEqual(fetched, ["A", "B", "C"], "A's songs do not count toward the target")
        self.assertEqual(groups, [("B", ["B1", "B2"]), ("C", ["C1", "C2"])])

    def test_walks_every_artist_when_none_are_kept(self):
        fetched = []
        groups = gather_until_usable("ABC", lambda a: fetched.append(a) or [a], lambda cs: [], 1)
        self.assertEqual((fetched, groups), (["A", "B", "C"], []))


class BuildPoolTest(unittest.TestCase):
    """Nov 18 2026: maybe_refresh found 0 candidates and refused to rebuild."""

    def build(self, extra_exclude, low_pop=0):
        with tempfile.TemporaryDirectory() as td:
            paths = mix.Paths(root=Path(td), state=Path(td) / "state")
            mx = mix.Mixer.__new__(mix.Mixer)
            mx.sp, mx.paths = _LibSp(), paths
            mx.cfg = mix.MixConfig(today=date(2026, 11, 18))
            mx._similar_cache = {}
            artists = [f"Artist {i:02d}" for i in range(60)]
            mx.similar_for = lambda name, limit=8: artists
            mx.popular_tracks_for = lambda artist, n=8: _artist_tracks(artist, n, low_pop)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                built = mix.Mixer.build(mx, {"id": "u1"}, extra_exclude=extra_exclude)
            return built, out.getvalue()

    def test_used_up_top_artists_do_not_empty_the_pool(self):
        # The top 40 similar artists' songs were all heard or offered already:
        # 320 raw hits, which is exactly where the old loop stopped searching.
        used = {c.track_id for i in range(40) for c in _artist_tracks(f"Artist {i:02d}")}
        built, log = self.build(used)
        self.assertNotIn("candidate pool after filters: 0", log)
        self.assertEqual(len(built), 40, log)
        self.assertTrue(all(c.track_id not in used for c in built))

    def test_fresh_library_searches_the_same_artists_as_before(self):
        # Old rule: stop at 8 x MIX_SIZE = 320 raw hits = 40 artists of 8.
        built, log = self.build(set())
        self.assertEqual(len(built), 40)
        self.assertIn("artists with unused candidates: 40 of 60", log)
        self.assertIn("candidate pool after filters: 240", log)

    def test_songs_below_the_popularity_floor_do_not_count(self):
        # Half of every artist's songs are below MIX_MIN_POPULARITY: the search
        # goes further instead of stopping on hits the pool will drop.
        built, log = self.build(set(), low_pop=4)
        self.assertIn("artists with unused candidates: 60 of 60", log)
        self.assertIn("candidate pool after filters: 240", log)
        self.assertTrue(all(c.popularity >= 55 for c in built))


if __name__ == "__main__":
    unittest.main()
