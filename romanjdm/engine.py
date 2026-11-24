# -*- coding: utf-8 -*-
"""Continuous movement engine (V2).

V1 problem: one finite motion per press (``_latched`` + ``_motion()`` ending at
Duration), "Repeat" restarted the motion and reset progress every cycle.

V2 design
---------
* ONE worker thread, started once, never restarted per click.
* While ARMED and Left + Right are both held, every tick integrates
  ``rate * envelope * dt`` (dt from time.perf_counter()) into a float
  accumulator and sends the whole-pixel part. The fractional remainder is kept,
  so slow or small rates are exact over time. Progress is never reset while the
  buttons stay down: no seam, no pause.
* X / Y are the distance per reference Duration, Speed multiplies the rate:
  ``rate = X * Speed / (Duration / 1000)`` px/s.
* Easing shapes only the START-UP ramp (first Duration/Speed seconds of a
  hold); after the ramp the rate is constant.
* Release either button, STOP, EMERGENCY STOP or F9: the very next tick
  (<= 8 ms) sends nothing and the remainder is discarded.
"""
from __future__ import annotations

import collections
import threading
from typing import Optional

from .hotkeys import HotkeyPoller
from .settings import MovementParams, sanitize
from .winapi import VK_LBUTTON, VK_RBUTTON, WinBackend

STATE_STOPPED = "STOPPED"
STATE_ARMED = "ARMED"
STATE_ACTIVE = "ACTIVE"
STATE_EMERGENCY = "EMERGENCY STOP"


class MouseEngine:
    IDLE_POLL_S = 0.004     # polling period while nothing is moving
    MAX_DT_S = 0.05         # cap one integration step (after a stall)
    FAIL_LIMIT = 20         # consecutive rejected SendInput calls -> disarm

    def __init__(self, settings: dict, backend=None):
        self._be = backend if backend is not None else WinBackend()
        self._settings = sanitize(settings)
        self._params = MovementParams.from_settings(self._settings)
        self._lock = threading.Lock()            # guards start/stop of the thread
        self._armed = threading.Event()
        self._emergency = threading.Event()
        self._quit = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # events for the GUI thread: ("message", str) / ("preset", int) / ("toggle", bool)
        self.events: collections.deque = collections.deque(maxlen=200)
        self.left_down = False
        self.right_down = False
        self.moving = False
        self._t0 = self._last = 0.0
        self._acc_x = self._acc_y = 0.0
        self._fails = 0
        self.hotkeys = HotkeyPoller(self._be, self._hk_preset, self._hk_toggle, self._hk_emergency)

    # ------------------------------------------------------------ public API
    def start(self) -> None:
        """Start the single worker thread (no-op if it is already running)."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            if self._quit.is_set():
                return                      # shutting down: never restart
            self._thread = threading.Thread(target=self._run, name="MouseEngine", daemon=True)
            self._thread.start()

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def state(self) -> str:
        if self._emergency.is_set():
            return STATE_EMERGENCY
        if not self._armed.is_set():
            return STATE_STOPPED
        return STATE_ACTIVE if self.moving else STATE_ARMED

    @property
    def armed(self) -> bool:
        return self._armed.is_set()

    def arm(self) -> None:
        """START. Also clears a latched EMERGENCY STOP (explicit user action)."""
        was_emergency = self._emergency.is_set()
        self._emergency.clear()
        if not self._armed.is_set() or was_emergency:
            self._armed.set()
            self._msg("Started - hold LEFT + RIGHT mouse to run")

    def disarm(self, reason: str = "Stopped") -> None:
        if self._armed.is_set():
            self._armed.clear()
            self._msg(reason)

    def emergency_stop(self, source: str = "button") -> None:
        self._armed.clear()
        self._emergency.set()
        self._msg(f"EMERGENCY STOP ({source})")

    def set_hotkeys_enabled(self, enabled: bool) -> None:
        self.hotkeys.enabled = bool(enabled)

    def update_settings(self, settings: dict) -> None:
        """Thread-safe live update (single reference swap, no new thread)."""
        s = sanitize(settings)
        params = MovementParams.from_settings(s)
        self._settings = s
        self._params = params

    def get_settings(self) -> dict:
        return dict(self._settings)

    def shutdown(self) -> None:
        self._armed.clear()
        self._quit.set()
        t = self._thread
        if t is not None and t.is_alive() and threading.current_thread() is not t:
            t.join(timeout=1.5)

    # --------------------------------------------------------------- hotkeys
    def _msg(self, text: str) -> None:
        self.events.append(("message", text))

    def _hk_preset(self, n: int) -> None:
        self.events.append(("preset", n))

    def _hk_toggle(self) -> None:
        if self._armed.is_set():
            self.disarm("Stopped (hotkey F8)")
        else:
            self.arm()

    def _hk_emergency(self) -> None:
        self.emergency_stop("hotkey F9")

    # ---------------------------------------------------------------- worker
    def _run(self) -> None:
        be = self._be
        be.begin_timer()
        try:
            while not self._quit.is_set():
                try:
                    delay = self.step(be.now())
                except Exception as exc:        # never let the thread die silently
                    self.moving = False
                    self._armed.clear()
                    self._msg(f"Engine error -> stopped: {exc!r}")
                    delay = 0.01
                be.sleep(delay)
        finally:
            self.moving = False
            be.end_timer()

    def step(self, now: float) -> float:
        """One engine iteration. Returns how long the caller should sleep."""
        be = self._be
        self.hotkeys.poll()
        left, right = be.key_down(VK_LBUTTON), be.key_down(VK_RBUTTON)
        self.left_down, self.right_down = left, right

        if not (self._armed.is_set() and left and right):
            if self.moving:                      # released / stopped -> stop NOW
                self.moving = False
                self._acc_x = self._acc_y = 0.0
            return self.IDLE_POLL_S

        p = self._params                         # one atomic read per tick
        if not self.moving:                      # new hold begins
            self.moving = True
            self._t0 = self._last = now
            self._acc_x = self._acc_y = 0.0
            self._fails = 0
            return p.interval

        dt = min(max(now - self._last, 0.0), self.MAX_DT_S)
        self._last = now
        env = p.envelope(now - self._t0)
        ax = self._acc_x + p.vx * env * dt
        ay = self._acc_y + p.vy * env * dt
        dx, dy = int(ax), int(ay)                # truncate toward zero
        if dx or dy:
            if be.send_move(dx, dy):
                ax -= dx
                ay -= dy
                self._fails = 0
            else:
                self._fails += 1
                if self._fails >= self.FAIL_LIMIT:
                    self._armed.clear()
                    self.moving = False
                    self._fails = 0
                    self._msg("Windows rejected input. If the target app runs as "
                              "Administrator, run this program as Administrator too.")
                    return self.IDLE_POLL_S
        self._acc_x, self._acc_y = ax, ay
        return p.interval
