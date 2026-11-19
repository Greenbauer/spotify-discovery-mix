"""Spotify 429 handling for builds: raise, cool down, cache searches.

Nov 18 2026: /search answered 429 QUOTA_EXCEEDED to every query, search
returned [] on any error, so each hourly rebuild looked like an empty pool
(exit 1), retried the next hour and burned more quota.
Run: .venv/bin/python -m unittest discover tests
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import mix  # noqa: E402
import rate_limit  # noqa: E402
from search_cache import SearchCache  # noqa: E402

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
QUOTA = {"error": {"status": 429, "message": "quota"}, "reason": "QUOTA_EXCEEDED"}


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


def spotify(resp):
    sp = mix.Spotify("token")
    sp.http.request = lambda *a, **k: resp
    return sp


class SearchRaisesTest(unittest.TestCase):
    def test_every_lookup_raises_on_429(self):
        calls = [
            lambda sp: sp.search_tracks("q"),
            lambda sp: sp.search_artist("Band"),
            lambda sp: sp.related_artists("id"),
            lambda sp: sp.artist_top_tracks("id"),
        ]
        for call in calls:
            with self.assertRaises(mix.SpotifyRateLimited) as ctx:
                call(spotify(FakeResp(429, QUOTA)))
            self.assertEqual(ctx.exception.reason, "QUOTA_EXCEEDED")
            self.assertIsNone(ctx.exception.retry_after)

    def test_retry_after_is_kept(self):
        with self.assertRaises(mix.SpotifyRateLimited) as ctx:
            spotify(FakeResp(429, QUOTA, {"Retry-After": "3600"})).search_tracks("q")
        self.assertEqual(ctx.exception.retry_after, 3600.0)

    def test_other_errors_still_read_as_no_results(self):
        self.assertEqual(spotify(FakeResp(400, {"error": "bad"})).search_tracks("q"), [])
        self.assertIsNone(spotify(FakeResp(404, {})).search_artist("Band"))

    def test_rate_limited_command_exits_75(self):
        def refused(paths):
            raise mix.SpotifyRateLimited("GET /search", None, "QUOTA_EXCEEDED")

        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(mix, "cmd_maybe_refresh", refused), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            rc = mix.main(["--state-dir", td, "--env-file", "/nonexistent", "maybe_refresh"])
        self.assertEqual(rc, mix.EXIT_RATE_LIMITED)
        self.assertIn("RATE_LIMITED", out.getvalue())


class CooldownTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_retry_after_is_honoured(self):
        until = rate_limit.record(self.state, "search", 900, "x", NOW)
        self.assertEqual(until, NOW + timedelta(seconds=900))

    def test_no_retry_after_backs_off_6h_doubling_to_48h(self):
        waits = []
        for _ in range(6):
            waits.append((rate_limit.record(self.state, "search", None, "QUOTA_EXCEEDED", NOW) - NOW)
                         .total_seconds() / 3600)
        self.assertEqual(waits, [6, 12, 24, 48, 48, 48])

    def test_clear_resets_the_doubling(self):
        rate_limit.record(self.state, "search", None, None, NOW)
        rate_limit.record(self.state, "search", None, None, NOW)
        rate_limit.clear(self.state, "search")
        self.assertFalse((self.state / rate_limit.FILE).exists())
        until = rate_limit.record(self.state, "search", None, None, NOW)
        self.assertEqual(until - NOW, timedelta(hours=6))

    def test_active_until_it_ends(self):
        rate_limit.record(self.state, "search", 60, "x", NOW)
        self.assertIsNotNone(rate_limit.active(self.state, "search", NOW + timedelta(seconds=59)))
        self.assertIsNone(rate_limit.active(self.state, "search", NOW + timedelta(seconds=60)))
        self.assertIsNone(rate_limit.active(self.state, "player", NOW), "scopes are separate")


class MaybeRefreshTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.paths = mix.Paths(root=Path(self.tmp.name), state=Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def run_refresh(self, build_fn):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = mix.cmd_maybe_refresh(self.paths, now=NOW, build_fn=build_fn,
                                       publish_fn=lambda paths: None)
        return rc, out.getvalue()

    def test_cooldown_skips_the_rebuild_with_no_api_call(self):
        rate_limit.record(self.paths.state, "search", None, "QUOTA_EXCEEDED", NOW)
        build = mock.Mock()
        rc, out = self.run_refresh(build)
        build.assert_not_called()
        self.assertEqual(rc, mix.EXIT_RATE_LIMITED)
        self.assertIn("RATE_LIMITED rebuild deferred", out)
        self.assertNotIn("MIX_FINISHED", out, "no ping while nothing can be rebuilt")

    def test_rate_limited_build_records_a_cooldown(self):
        def refused(paths, extra_exclude=None):
            raise mix.SpotifyRateLimited("GET /search", None, "QUOTA_EXCEEDED")

        with self.assertRaises(mix.SpotifyRateLimited):
            self.run_refresh(refused)
        cool = rate_limit.active(self.paths.state, "search", NOW + timedelta(hours=5))
        self.assertEqual(cool["reason"], "QUOTA_EXCEEDED")

    def test_successful_rebuild_clears_the_cooldown(self):
        rate_limit.record(self.paths.state, "search", 1, None, NOW - timedelta(hours=1))
        rc, out = self.run_refresh(lambda paths, extra_exclude=None: None)
        self.assertEqual(rc, 0)
        self.assertIn("NEW_MIX", out)
        self.assertFalse((self.paths.state / rate_limit.FILE).exists())


class RollTopUpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.paths = mix.Paths(root=Path(self.tmp.name), state=Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def top_up(self, build_fn):
        sp = mock.Mock()
        sp.me.return_value = {"id": "u"}
        with contextlib.redirect_stdout(io.StringIO()):
            return mix._build_roll_replacements(self.paths, sp, mix.MixConfig(),
                                                extra_exclude=set(), need=2, build_fn=build_fn)

    def test_cooldown_skips_the_top_up_search(self):
        rate_limit.record(self.paths.state, "search", 3600, "x")
        build = mock.Mock()
        self.assertEqual(self.top_up(build), [])
        build.assert_not_called()

    def test_rate_limited_top_up_returns_nothing_and_cools_down(self):
        def refused(user, extra_exclude=None, target_size=None):
            raise mix.SpotifyRateLimited("GET /search", None, "QUOTA_EXCEEDED")

        self.assertEqual(self.top_up(refused), [])
        self.assertIsNotNone(rate_limit.active(self.paths.state, "search"))


class _SearchSp:
    caps = mix.SpotifyCaps()

    def __init__(self):
        self.track_calls = 0
        self.artist_calls = 0

    def search_tracks(self, q, limit=5):
        self.track_calls += 1
        return [{"id": "T", "uri": "spotify:track:T", "name": "Song", "popularity": 70,
                 "album": {"images": ["big"]}, "artists": [{"id": "a", "name": "Band"}]}]

    def search_artist(self, name):
        self.artist_calls += 1
        return {"id": "a", "name": name, "followers": {"total": 5}}


class SearchCacheTest(unittest.TestCase):
    def mixer(self, state, sp):
        mx = mix.Mixer.__new__(mix.Mixer)
        mx.sp, mx.paths, mx.cfg = sp, mix.Paths(root=state, state=state), mix.MixConfig()
        return mx

    def test_repeat_searches_hit_the_cache_across_runs(self):
        with tempfile.TemporaryDirectory() as td:
            sp = _SearchSp()
            first = self.mixer(Path(td), sp)
            hits = first._tracks('artist:"Band"', 10)
            self.assertEqual(first._artist("Band"), {"id": "a", "name": "Band"})
            first._tracks('artist:"Band"', 10)
            self.assertEqual((sp.track_calls, sp.artist_calls), (1, 1))
            self.assertEqual(hits[0]["popularity"], 70)
            self.assertNotIn("album", hits[0], "only the fields the mixer reads are stored")
            first.search.save()
            second = self.mixer(Path(td), sp)
            second._tracks('artist:"Band"', 10)
            second._artist("band")
            self.assertEqual((sp.track_calls, sp.artist_calls), (1, 1), "the next build reuses it")

    def test_expired_entries_are_refetched_and_pruned(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "search_cache.json"
            path.write_text(json.dumps({"t10:old": {"ts": 0, "v": []}}))
            cache = SearchCache(path, ttl_days=7)
            self.assertEqual(cache.get_or_fetch("t10:old", lambda: ["new"]), ["new"])
            cache.entries["t10:gone"] = {"ts": 0, "v": []}
            cache.save()
            self.assertEqual(set(json.loads(path.read_text())), {"t10:old"})

    def test_a_429_is_not_cached(self):
        cache = SearchCache(None)

        def refused():
            raise mix.SpotifyRateLimited("GET /search")

        with self.assertRaises(mix.SpotifyRateLimited):
            cache.get_or_fetch("k", refused)
        self.assertEqual(cache.get_or_fetch("k", lambda: ["ok"]), ["ok"])

    def test_build_saves_the_cache_even_when_a_429_aborts_it(self):
        with tempfile.TemporaryDirectory() as td:
            mx = self.mixer(Path(td), _SearchSp())
            mx._tracks("q", 5)

            def refused(*a, **k):
                raise mix.SpotifyRateLimited("GET /search")

            with mock.patch.object(mix.Mixer, "_build", refused), \
                    contextlib.redirect_stdout(io.StringIO()), \
                    self.assertRaises(mix.SpotifyRateLimited):
                mx.build({"id": "u"})
            self.assertIn("t5:q", json.loads((Path(td) / "search_cache.json").read_text()))


if __name__ == "__main__":
    unittest.main()
