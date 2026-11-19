"""Tests for the live skip watcher. Run: .venv/bin/python -m unittest discover tests"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import random
import sys
import tempfile
import unittest
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import live_watch as lw  # noqa: E402
import mix  # noqa: E402

_spec = importlib.util.spec_from_file_location("watcher_health", ROOT / "scripts" / "watcher_health.py")
wh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wh)

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


class ClassifyTest(unittest.TestCase):
    def test_early_stop_is_a_skip(self):
        self.assertEqual(lw.classify(10_000, 200_000, S), "skipped")
        self.assertEqual(lw.classify(29_900, 200_000, S), "skipped")

    def test_past_thirty_seconds_is_heard(self):
        self.assertEqual(lw.classify(30_000, 200_000, S), "heard")
        self.assertEqual(lw.classify(195_000, 200_000, S), "heard")

    def test_short_song_uses_half_its_length(self):
        self.assertEqual(lw.classify(19_000, 40_000, S), "skipped")
        self.assertEqual(lw.classify(21_000, 40_000, S), "heard")

    def test_unknown_length_falls_back_to_seconds(self):
        self.assertEqual(lw.classify(20_000, 0, S), "skipped")
        self.assertEqual(lw.classify(31_000, 0, S), "heard")

    def test_thresholds_come_from_env(self):
        env = {"LIVE_SKIP_SECONDS": "45", "LIVE_SKIP_RATIO": "0.3", "MIX_ROLL_DELAY_MIN": "2"}
        with mock.patch.dict("os.environ", env):
            s = lw.Settings.from_env()
        self.assertEqual((s.skip_seconds, s.skip_ratio, s.heard_delay_s), (45.0, 0.3, 120.0))


class SnapshotTest(unittest.TestCase):
    def test_mix_context_counts(self):
        self.assertTrue(snap("A").from_mix)

    def test_mix_track_from_another_context_counts(self):
        self.assertTrue(snap("A", ctx="spotify:album:X", mix_ids={"A"}).from_mix)

    def test_other_playback_does_not_count(self):
        self.assertFalse(snap("A", ctx="spotify:album:X").from_mix)

    def test_nothing_or_podcast_is_none(self):
        self.assertIsNone(lw.parse_snapshot(None, MIX_URI, set()))
        self.assertIsNone(snap("E", kind="episode"))


class TrackerTest(unittest.TestCase):
    def setUp(self):
        self.t = lw.Tracker(S)

    def test_quick_change_is_a_skip(self):
        self.assertIsNone(self.t.observe(snap("A", 3)))
        self.assertIsNone(self.t.observe(snap("A", 8)))
        done = self.t.observe(snap("B", 1))
        self.assertEqual((done.play.track_id, done.outcome), ("A", "skipped"))

    def test_listened_change_is_heard(self):
        self.t.observe(snap("A", 5))
        self.t.observe(snap("A", 120))
        self.assertEqual(self.t.observe(snap("B", 1)).outcome, "heard")

    def test_seek_back_keeps_furthest_point(self):
        self.t.observe(snap("A", 90))
        self.t.observe(snap("A", 2))
        self.assertEqual(self.t.observe(snap("B")).outcome, "heard")

    def test_non_mix_track_is_ignored(self):
        self.t.observe(snap("A", 3, ctx="spotify:album:X"))
        self.assertIsNone(self.t.observe(snap("B")))

    def test_nothing_playing_keeps_the_pending_track(self):
        self.t.observe(snap("A", 5))
        self.assertIsNone(self.t.observe(None))
        self.assertEqual(self.t.observe(snap("B")).play.track_id, "A")

    def test_idle_flush_logs_only_a_heard_track(self):
        self.t.observe(snap("A", 5, playing=False))
        self.assertIsNone(self.t.flush_idle(), "a pause is not a skip")
        self.t.observe(snap("C", 100, playing=False))
        self.assertEqual(self.t.flush_idle().outcome, "heard")
        self.assertIsNone(self.t.current)


class RollSchedulerTest(unittest.TestCase):
    def setUp(self):
        self.r = lw.RollScheduler(lw.Settings(roll_gap_s=60, heard_delay_s=300))

    def test_skip_rolls_now(self):
        self.r.add("skipped", 1000)
        self.assertTrue(self.r.due(1000))

    def test_skips_are_throttled_to_one_roll_a_minute(self):
        self.r.add("skipped", 1000)
        self.r.ran(1000, ok=True)
        self.r.add("skipped", 1010)
        self.assertFalse(self.r.due(1059))
        self.assertTrue(self.r.due(1060))

    def test_heard_waits_for_the_delay(self):
        self.r.add("heard", 1000)
        self.assertFalse(self.r.due(1300))
        self.assertTrue(self.r.due(1000 + 300 + lw.HEARD_ROLL_MARGIN_S))

    def test_heard_roll_survives_an_earlier_skip_roll(self):
        self.r.add("heard", 1000)
        self.r.add("skipped", 1001)
        self.r.ran(1001, ok=True)
        self.assertEqual(self.r.next_at(), 1000 + 300 + lw.HEARD_ROLL_MARGIN_S)

    def test_failed_roll_retries(self):
        self.r.add("skipped", 1000)
        self.r.ran(1000, ok=False)
        self.assertEqual(self.r.next_at(), 1000 + lw.ROLL_RETRY_S)


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


class WatcherTest(unittest.TestCase):
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

    def test_skip_is_logged_and_rolls_at_once(self):
        w = self.watcher([FakeResp(200, body("A", 4)), FakeResp(200, body("B", 1))])
        with mock.patch.object(lw, "run_roll", return_value=True) as roll, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(w.step(), S.poll_mix_s)
            roll.assert_not_called()
            w.step()
            roll.assert_called_once()
        plays = mix.read_json(self.paths.played, {})["plays"]
        self.assertEqual([(p["track_id"], p["outcome"], p["source"]) for p in plays],
                         [("A", "skipped", "live-watch")])
        self.assertEqual(w.health["counts"]["rolls"], 1)
        w.write_health()
        report = wh.live_from_state(self.paths.state)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["counts"]["skipped"], 1)

    def test_heard_is_logged_but_roll_waits(self):
        w = self.watcher([FakeResp(200, body("A", 100)), FakeResp(200, body("B", 1))])
        with mock.patch.object(lw, "run_roll", return_value=True) as roll, \
                contextlib.redirect_stdout(io.StringIO()):
            w.step()
            w.step()
            roll.assert_not_called()
        self.assertEqual(mix.read_json(self.paths.played, {})["plays"][0]["outcome"], "heard")
        self.assertIsNotNone(w.rolls.next_at())

    def test_rate_limit_honours_retry_after(self):
        w = self.watcher([FakeResp(429, headers={"Retry-After": "40"})])
        self.assertEqual(w.step(), 40.0)

    def test_nothing_playing_backs_off(self):
        w = self.watcher([FakeResp(204)])
        self.assertEqual(w.step(), lw.POLL_IDLE_S)

    def test_other_playback_polls_slower(self):
        w = self.watcher([FakeResp(200, body("Z", 5, ctx="spotify:album:X"))])
        self.assertEqual(w.step(), lw.POLL_OTHER_S)

    def test_auth_failure_is_flagged_once_and_clears(self):
        w = self.watcher([FakeResp(401, {"error": "x"}), FakeResp(401, {"error": "x"}), FakeResp(204)])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(w.step(), lw.AUTH_RETRY_S)
            w.step()
        self.assertEqual(out.getvalue().count("AUTH_FAILED"), 1)
        w.write_health()
        self.assertTrue(wh.live_from_state(self.paths.state)["needs_user_ping"])
        w.step()
        w.write_health()
        self.assertTrue(wh.live_from_state(self.paths.state)["ok"])


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
        with mock.patch.object(lw, "run_roll", return_value=True) as roll:
            self.assertEqual(w.step(), 7200.0)
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

    def test_paused_mix_track_keeps_fast_polling(self):
        # Pause at 12 s, resume and listen to 70 s, then skip: must be heard.
        w = self.watcher([
            FakeResp(200, body("A", 12)),
            FakeResp(200, body("A", 12, playing=False)),
            FakeResp(200, body("A", 70)),
            FakeResp(200, body("B", 1)),
        ])
        with mock.patch.object(lw, "run_roll", return_value=True), \
                contextlib.redirect_stdout(io.StringIO()):
            w.step()
            self.assertEqual(w.step(), S.poll_mix_s, "paused on a mix track")
            w.step()
            w.step()
        self.assertEqual(mix.read_json(self.paths.played, {})["plays"][0]["outcome"], "heard")

    def test_playing_without_a_track_is_not_idle(self):
        w = self.watcher([FakeResp(200, {"is_playing": True, "item": None, "progress_ms": 0})])
        self.assertEqual(w.step(), lw.POLL_OTHER_S)


class LockTest(unittest.TestCase):
    def test_record_play_waits_for_the_plays_lock(self):
        import fcntl

        with tempfile.TemporaryDirectory() as td:
            state = Path(td)
            with lw.state_lock(state, "plays"):
                with open(state / "plays.lock", "w") as fh:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assertTrue(getattr(mix.harvest_plays, "__wrapped__", None), "harvest_plays is locked")
        self.assertTrue(getattr(mix.ingest_ui_nowplaying, "__wrapped__", None))
        self.assertTrue(getattr(mix.cmd_roll_playlist, "__wrapped__", None))


class LiveHealthTest(unittest.TestCase):
    NOW = datetime(2026, 11, 18, 23, 0, tzinfo=timezone.utc)

    def test_missing_watcher_needs_restart(self):
        r = wh.assess_live(health=None, alive_mtime_at=None, now=self.NOW)
        self.assertEqual((r["ok"], r["needs_restart"], r["needs_user_ping"]), (False, True, False))

    def test_stale_watcher_needs_restart(self):
        r = wh.assess_live(health={}, alive_mtime_at=self.NOW - timedelta(minutes=30), now=self.NOW)
        self.assertTrue(r["needs_restart"])

    def test_fresh_watcher_is_ok(self):
        r = wh.assess_live(health={}, alive_mtime_at=self.NOW - timedelta(minutes=1), now=self.NOW)
        self.assertTrue(r["ok"])


class MixIntegrationTest(unittest.TestCase):
    NOW = datetime(2026, 11, 18, 23, 0, tzinfo=timezone.utc)

    def playlist(self):
        return [{"id": t, "name": f"Song {t}", "artists": [{"name": f"Artist {t}"}]} for t in "ABC"]

    def test_skipped_row_rolls_off_without_the_delay(self):
        just_now = self.NOW.isoformat()
        played = {"plays": [
            {"track_id": "A", "name": "Song A", "played_at": just_now, "outcome": "skipped"},
            {"track_id": "B", "name": "Song B", "played_at": just_now, "outcome": "heard"},
        ]}
        plan = mix.plan_roll(self.playlist(), played, delay_min=5, mix_size=3, now=self.NOW)
        self.assertEqual([t["id"] for t in plan.removed], ["A"])
        later = mix.plan_roll(self.playlist(), played, delay_min=5, mix_size=3,
                              now=self.NOW + timedelta(minutes=5))
        self.assertEqual(sorted(t["id"] for t in later.removed), ["A", "B"])

    def test_skipped_track_is_never_picked_again(self):
        class Lib:
            caps = mix.SpotifyCaps()

            def created_playlists(self, uid):
                return [{"id": "p1", "name": "Deep Cuts"}]

            def playlist_items(self, pid):
                return [{"id": f"s{i}", "name": f"Seed {i}", "artists": [{"name": "Seed Band"}]}
                        for i in range(2)]

            def liked_tracks(self):
                return []

        with tempfile.TemporaryDirectory() as td:
            paths = mix.Paths(root=Path(td), state=Path(td))
            mix.write_json(paths.played, {"plays": [
                {"track_id": "SKIP", "name": "Skipped Song", "artists": ["New Band"],
                 "outcome": "skipped"}]})
            mx = mix.Mixer.__new__(mix.Mixer)
            mx.sp, mx.paths, mx.cfg = Lib(), paths, mix.MixConfig(today=self.NOW.date())
            mx._similar_cache = {}
            mx.similar_for = lambda name, limit=8: ["New Band"]
            mx.popular_tracks_for = lambda artist, n=8: [
                mix.Candidate(t, f"spotify:track:{t}", name, ["New Band"], ["nb"], 70, "s")
                for t, name in [("SKIP", "Skipped Song"), ("OTHER_ID", "Skipped Song"),
                                ("KEEP", "Fresh Song")]
            ]
            with contextlib.redirect_stdout(io.StringIO()):
                built = mix.Mixer.build(mx, {"id": "u"}, target_size=5)
        self.assertEqual([c.track_id for c in built], ["KEEP"],
                         "skipped id and its other release id stay out")

    def test_append_heard_keeps_outcome_and_dedupes(self):
        played = {"plays": []}
        self.assertTrue(mix._append_heard(played, track_id="A", uri=None, name="a",
                                          played_at="t", source="live-watch", outcome="skipped"))
        self.assertFalse(mix._append_heard(played, track_id="A", uri=None, name="a",
                                           played_at="t", source="recently-played"))
        self.assertEqual(played["plays"][0]["outcome"], "skipped")

    def test_skips_down_weight_an_artist(self):
        played = {"plays": [
            {"track_id": "x", "artists": ["Skipped Band"], "outcome": "skipped"},
            {"track_id": "y", "artists": ["Skipped Band"], "outcome": "skipped"},
            {"track_id": "z", "artists": ["Liked Band"]},
        ]}
        skips = mix.skipped_artist_counts(played)
        self.assertEqual(skips, Counter({"skipped band": 2}))

        def cand(tid, artist):
            return mix.Candidate(track_id=tid, uri=f"spotify:track:{tid}", name=tid,
                                 artists=[artist], artist_ids=[artist], popularity=60,
                                 source="t", measured=True)

        self.assertEqual(mix._skip_factor(cand("1", "Skipped Band"), skips), 0.25)
        self.assertEqual(mix._skip_factor(cand("2", "Liked Band"), skips), 1.0)
        pool = [cand("s", "Skipped Band"), cand("l", "Liked Band")]
        firsts = Counter(
            mix.select_mix_tracks(pool, size=1, max_per_artist=2, max_path_c=0,
                                  rng=random.Random(i), skips=skips)[0].artists[0]
            for i in range(400)
        )
        self.assertGreater(firsts["Liked Band"], firsts["Skipped Band"] * 2)


if __name__ == "__main__":
    unittest.main()
