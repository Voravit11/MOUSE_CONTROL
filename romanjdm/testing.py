# -*- coding: utf-8 -*-
"""Fake backend: lets the engine and GUI run without Windows (unit tests,
`--selftest`). It never touches the real mouse."""
from __future__ import annotations

import time


class FakeBackend:
    """Implements the same interface as winapi.WinBackend.

    simulated=True  -> deterministic clock: sleep() just advances `t`.
    simulated=False -> real perf_counter clock (used for threaded tests).
    """

    def __init__(self, simulated: bool = False):
        self.simulated = simulated
        self.t = 0.0
        self.keys: set[int] = set()
        self.moves: list[tuple[float, int, int]] = []   # (time, dx, dy)
        self.accept = True                               # False -> SendInput "fails"
        self.timer_depth = 0

    # -- input side -------------------------------------------------------
    def key_down(self, vk: int) -> bool:
        return vk in self.keys

    def press(self, *vks: int) -> None:
        self.keys.update(vks)

    def release(self, *vks: int) -> None:
        self.keys.difference_update(vks)

    def send_move(self, dx: int, dy: int) -> bool:
        if not self.accept:
            return False
        self.moves.append((self.now(), int(dx), int(dy)))
        return True

    # -- time side --------------------------------------------------------
    def now(self) -> float:
        return self.t if self.simulated else time.perf_counter()

    def sleep(self, seconds: float) -> None:
        if self.simulated:
            self.t += max(0.0, seconds)
        elif seconds > 0:
            time.sleep(seconds)

    def begin_timer(self) -> None:
        self.timer_depth += 1

    def end_timer(self) -> None:
        self.timer_depth -= 1

    # -- helpers ----------------------------------------------------------
    def total(self) -> tuple[int, int]:
        return sum(m[1] for m in self.moves), sum(m[2] for m in self.moves)

    def clear(self) -> None:
        self.moves.clear()
