# -*- coding: utf-8 -*-
import threading
import time
import unittest

from romanjdm.engine import (MouseEngine, STATE_ACTIVE, STATE_ARMED, STATE_EMERGENCY, STATE_STOPPED)
from romanjdm.testing import FakeBackend
from romanjdm.winapi import VK_F1, VK_F2, VK_F8, VK_F9, VK_LBUTTON, VK_RBUTTON, VK_MENU, VK_F4


def run(engine, be, seconds):
    end = be.t + seconds
    while be.t < end:
        be.sleep(engine.step(be.now()))


def make(settings=None, **kw):
    be = FakeBackend(simulated=True)
    s = {"x": 10, "y": -20, "duration": 300, "speed": 1.0, "smoothness": 80, "easing": "linear"}
    s.update(settings or {})
    e = MouseEngine(s, be)
    return e, be


class ContinuousMovement(unittest.TestCase):
    def test_total_distance_follows_rate_over_many_durations(self):
        e, be = make()
        e.arm(); be.press(VK_LBUTTON, VK_RBUTTON)
        run(e, be, 3.0)                      # 10 reference durations
        dx, dy = be.total()
        self.assertAlmostEqual(dx, 100, delta=2)
        self.assertAlmostEqual(dy, -200, delta=2)

    def test_no_seam_at_duration_boundary(self):
        e, be = make({"x": 0, "y": 60, "duration": 300})
        e.arm(); be.press(VK_LBUTTON, VK_RBUTTON)
        run(e, be, 1.5)
        # rate per 100 ms window must stay constant before / around / after 300 ms
        def window(t0):
            return sum(m[2] for m in be.moves if t0 <= m[0] < t0 + 0.1)
        w = [window(t) for t in (0.1, 0.25, 0.3, 0.5, 1.0)]
        self.assertTrue(all(abs(x - 20) <= 2 for x in w), w)

    def test_no_pause_between_sends(self):
        e, be = make({"x": 0, "y": 600, "duration": 300})
        e.arm(); be.press(VK_LBUTTON, VK_RBUTTON)
        run(e, be, 2.0)
        gaps = [b[0] - a[0] for a, b in zip(be.moves, be.moves[1:])]
        self.assertLess(max(gaps), 0.02)

    def test_signs_zero_and_diagonal(self):
        for x, y in ((-30, 0), (0, 30), (0, 0), (-15, -45), (45, 15)):
            e, be = make({"x": x, "y": y})
            e.arm(); be.press(VK_LBUTTON, VK_RBUTTON)
            run(e, be, 0.9)
            dx, dy = be.total()
            self.assertAlmostEqual(dx, x * 3, delta=2)
            self.assertAlmostEqual(dy, y * 3, delta=2)

    def test_speed_multiplier(self):
        e, be = make({"x": 0, "y": 30, "speed": 2.0})
        e.arm(); be.press(VK_LBUTTON, VK_RBUTTON)
        run(e, be, 0.3)
        self.assertAlmostEqual(be.total()[1], 60, delta=2)

    def test_sub_pixel_rate_is_not_lost(self):
        e, be = make({"x": 1, "y": 0, "duration": 5000})   # 0.2 px/s
        e.arm(); be.press(VK_LBUTTON, VK_RBUTTON)
        run(e, be, 12.0)                                  # 2.4 px in total
        self.assertEqual(be.total()[0], 2)

    def test_easing_only_shapes_startup(self):
        for mode in ("ease_in", "ease_out", "ease_in_out"):
            e, be = make({"x": 0, "y": 60, "duration": 300, "easing": mode})
            e.arm(); be.press(VK_LBUTTON, VK_RBUTTON)
            run(e, be, 1.5)
            late = sum(m[2] for m in be.moves if 1.0 <= m[0] < 1.1)
            self.assertAlmostEqual(late, 20, delta=2, msg=mode)       # steady after the ramp
            early = sum(m[2] for m in be.moves if m[0] < 0.1)
            self.assertLess(early, 20, msg=mode) if mode != "ease_out" else self.assertGreater(early, 0)

    def test_live_settings_change(self):
        e, be = make({"x": 0, "y": 30})
        e.arm(); be.press(VK_LBUTTON, VK_RBUTTON)
        run(e, be, 0.5); n = len(be.moves)
        e.update_settings({"x": 0, "y": 90, "duration": 300})
        run(e, be, 0.3)
        recent = sum(m[2] for m in be.moves[n:])
        self.assertAlmostEqual(recent, 90, delta=3)


class Stopping(unittest.TestCase):
    def test_release_either_button_stops_immediately(self):
        for btn in (VK_LBUTTON, VK_RBUTTON):
            e, be = make()
            e.arm(); be.press(VK_LBUTTON, VK_RBUTTON)
            run(e, be, 0.5)
            self.assertEqual(e.state, STATE_ACTIVE)
            be.release(btn)
            n = len(be.moves)
            e.step(be.now())
            self.assertEqual(len(be.moves), n)
            self.assertFalse(e.moving)
            self.assertEqual(e.state, STATE_ARMED)

    def test_not_armed_never_moves(self):
        e, be = make()
        be.press(VK_LBUTTON, VK_RBUTTON)
        run(e, be, 1.0)
        self.assertEqual(be.moves, [])
        self.assertEqual(e.state, STATE_STOPPED)

    def test_repress_starts_again_without_stale_remainder(self):
        e, be = make({"x": 0, "y": 30})
        e.arm(); be.press(VK_LBUTTON, VK_RBUTTON); run(e, be, 0.3)
        be.release(VK_LBUTTON); run(e, be, 0.1); n = len(be.moves)
        run(e, be, 0.5)
        self.assertEqual(len(be.moves), n)            # nothing while released
        be.press(VK_LBUTTON); run(e, be, 0.3)
        self.assertGreater(len(be.moves), n)

    def test_emergency_stop_latches_until_start(self):
        e, be = make()
        e.arm(); be.press(VK_LBUTTON, VK_RBUTTON); run(e, be, 0.2)
        e.emergency_stop("test")
        n = len(be.moves); run(e, be, 0.5)
        self.assertEqual(len(be.moves), n)
        self.assertEqual(e.state, STATE_EMERGENCY)
        e.arm()
        self.assertNotEqual(e.state, STATE_EMERGENCY)
        run(e, be, 0.2)
        self.assertGreater(len(be.moves), n)

    def test_f9_hotkey_emergency_even_with_hotkeys_disabled(self):
        e, be = make()
        e.set_hotkeys_enabled(False)
        e.arm(); be.press(VK_F9); e.step(be.now())
        self.assertEqual(e.state, STATE_EMERGENCY)

    def test_input_rejected_disarms_safely(self):
        e, be = make()
        be.accept = False
        e.arm(); be.press(VK_LBUTTON, VK_RBUTTON)
        run(e, be, 1.0)
        self.assertFalse(e.armed)
        self.assertFalse(e.moving)


class Hotkeys(unittest.TestCase):
    def test_f1_f2_emit_preset_events_once_per_press(self):
        e, be = make()
        be.press(VK_F2)
        for _ in range(10):
            e.step(be.now())
        be.release(VK_F2); e.step(be.now())
        be.press(VK_F1); e.step(be.now())
        presets = [p for k, p in e.events if k == "preset"]
        self.assertEqual(presets, [2, 1])

    def test_modifier_blocks_alt_f4(self):
        e, be = make()
        be.press(VK_MENU, VK_F4); e.step(be.now())
        self.assertEqual([x for x in e.events if x[0] == "preset"], [])

    def test_hotkeys_can_be_disabled(self):
        e, be = make()
        e.set_hotkeys_enabled(False)
        be.press(VK_F1, VK_F8); e.step(be.now())
        self.assertEqual([x for x in e.events if x[0] == "preset"], [])
        self.assertFalse(e.armed)

    def test_f8_toggles(self):
        e, be = make()
        be.press(VK_F8); e.step(be.now()); be.release(VK_F8); e.step(be.now())
        self.assertTrue(e.armed)
        be.press(VK_F8); e.step(be.now())
        self.assertFalse(e.armed)


class Threading(unittest.TestCase):
    def test_single_thread_real_time_and_clean_shutdown(self):
        before = threading.active_count()
        be = FakeBackend(simulated=False)
        e = MouseEngine({"x": 0, "y": 100, "duration": 100}, be)
        for _ in range(5):
            e.start()
        self.assertEqual(sum(t.name == "MouseEngine" for t in threading.enumerate()), 1)
        e.arm(); be.press(VK_LBUTTON, VK_RBUTTON)
        time.sleep(0.4)
        be.release(VK_RBUTTON)
        time.sleep(0.05)
        moved = be.total()[1]
        self.assertGreater(moved, 200)                # ~ 1000 px/s * 0.4 s
        time.sleep(0.1)
        self.assertEqual(be.total()[1], moved)        # nothing after release
        e.shutdown()
        self.assertFalse(e.is_alive())
        self.assertEqual(threading.active_count(), before)
        self.assertEqual(be.timer_depth, 0)

    def test_cpu_idle_poll_is_not_busy(self):
        be = FakeBackend(simulated=False)
        e = MouseEngine({}, be)
        calls = {"n": 0}
        orig = be.key_down
        def counting(vk):
            calls["n"] += 1
            return orig(vk)
        be.key_down = counting
        e.start(); time.sleep(0.5); e.shutdown()
        self.assertLess(calls["n"], 8 * 140)          # ~<= 250 polls/s * 8 keys

if __name__ == "__main__":
    unittest.main()
