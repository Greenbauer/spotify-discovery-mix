"""Live watcher: rate limits, outages, auth and long waits.
Run: .venv/bin/python -m unittest discover tests"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

from live_fixtures import ROOT, S, FakeResp, WatcherBase, body  # noqa: E402

import live_watch as lw  # noqa: E402
import mix  # noqa: E402
import rate_limit  # noqa: E402

_spec = importlib.util.spec_from_file_location("watcher_health", ROOT / "scripts" / "watcher_health.py")
wh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wh)


class WatcherLimitsTest(WatcherBase):
    def test_outage_is_not_an_auth_failure(self):
        w = self.watcher([RuntimeError("HTTP GET x failed after retries"),
                          RuntimeError("token refresh -> 503: busy")])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(w.step(), lw.ERROR_RETRY_S)
            self.assertEqual(w.step(), lw.ERROR_RETRY_S)
        self.assertNotIn("AUTH_FAILED", out.getvalue())
        self.assertFalse(w.auth_failed)

    def test_refused_refresh_token_is_an_auth_failure(self):
        w = self.watcher([RuntimeError("token refresh -> 400: invalid_grant")])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(w.step(), lw.AUTH_RETRY_S)
        self.assertTrue(w.auth_failed)

    def test_long_429_waits_it_out_and_does_not_roll(self):
        w = self.watcher([FakeResp(429, headers={"Retry-After": "7200"})])
        w.rolls.add("skipped", 0.0)  # a roll is overdue
        with mock.patch.object(lw, "run_roll", return_value=(True, lw.ROLL_RETRY_S)) as roll, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertAlmostEqual(w.step(), 7200.0, delta=1)
            roll.assert_not_called()
        self.assertIn("backing_off_until", w.health)

    def test_auth_flag_survives_a_rate_limit(self):
        w = self.watcher([FakeResp(401, {}), FakeResp(429, headers={"Retry-After": "5"})])
        with contextlib.redirect_stdout(io.StringIO()):
            w.step()
            w.step()
        self.assertTrue(w.auth_failed)

    def test_long_wait_keeps_health_fresh(self):
        w = self.watcher([])
        with mock.patch.object(lw, "HEALTH_TOUCH_S", 0.01):
            w.nap(0.035)
        report = wh.live_from_state(self.paths.state)
        self.assertFalse(report["needs_restart"], report)

    def test_quota_429_without_retry_after_backs_off_hours_and_persists(self):
        quota = FakeResp(429, {"error": {"status": 429, "reason": "QUOTA_EXCEEDED"}})
        w = self.watcher([quota, FakeResp(204)])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertAlmostEqual(w.step(), 6 * 3600, delta=2)
        cool = rate_limit.active(self.paths.state, "player")
        self.assertEqual(cool["reason"], "QUOTA_EXCEEDED")
        restarted = self.watcher([])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertAlmostEqual(restarted.startup_wait(), 6 * 3600, delta=2,
                                   msg="a restart does not poll inside the cooldown")
        with contextlib.redirect_stdout(io.StringIO()):
            w.step()  # the next poll succeeds
        self.assertIsNone(rate_limit.active(self.paths.state, "player"))

    def test_rate_limited_roll_waits_for_its_cooldown(self):
        def refused(paths, sp=None):
            raise mix.SpotifyRateLimited("PUT /playlists/x/items", 3600, "QUOTA_EXCEEDED")

        with mock.patch.object(mix, "cmd_roll_playlist", refused), \
                contextlib.redirect_stdout(io.StringIO()):
            ok, retry_s = lw.run_roll(self.paths, None)
        self.assertFalse(ok)
        self.assertAlmostEqual(retry_s, 3600, delta=2)
        with mock.patch.object(mix, "cmd_roll_playlist", return_value=0):
            self.assertEqual(lw.run_roll(self.paths, None), (True, lw.ROLL_RETRY_S))
        self.assertIsNone(rate_limit.active(self.paths.state, "roll"),
                          "a good roll clears the cooldown and its doubling")
        self.assertFalse((self.paths.state / rate_limit.FILE).exists())

    def test_new_skips_do_not_roll_during_a_roll_cooldown(self):
        rate_limit.record(self.paths.state, "roll", 3600, "QUOTA_EXCEEDED")
        w = self.watcher([FakeResp(200, body("A", 4)), FakeResp(200, body("B", 1))])
        with mock.patch.object(lw, "run_roll", return_value=(True, lw.ROLL_RETRY_S)) as roll, \
                contextlib.redirect_stdout(io.StringIO()):
            w.step()
            self.assertEqual(w.step(), S.poll_mix_s, "a due roll does not shorten the poll")
            roll.assert_not_called()
        self.assertEqual(mix.read_json(self.paths.played, {})["plays"][0]["outcome"], "skipped",
                         "the skip is still recorded; the hourly roll or a later one removes it")

