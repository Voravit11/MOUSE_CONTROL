# -*- coding: utf-8 -*-
"""Global hotkeys by polling (GetAsyncKeyState). No hook / RegisterHotKey is
used, so this program never "steals" a key from another program.

Collision protection
--------------------
* A hotkey fires only on the rising edge (key just went down), never while held.
* If Shift / Ctrl / Alt / Win is held, F1-F4 and F8 are ignored. This keeps
  shortcuts of other programs working (for example Alt+F4 closes a window and
  must never switch to Preset 4).
* "Global hotkeys" can be switched off in the GUI: F1-F4 and F8 stop working.
* F9 (EMERGENCY STOP) is deliberately never disabled.
"""
from __future__ import annotations

from typing import Callable

from .winapi import (
    VK_CONTROL, VK_F1, VK_F2, VK_F3, VK_F4, VK_F8, VK_F9, VK_LWIN, VK_MENU,
    VK_RWIN, VK_SHIFT,
)

PRESET_KEYS = {VK_F1: 1, VK_F2: 2, VK_F3: 3, VK_F4: 4}
MODIFIER_KEYS = (VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN)
WATCHED = tuple(PRESET_KEYS) + (VK_F8, VK_F9)


class HotkeyPoller:
    def __init__(self, backend,
                 on_preset: Callable[[int], None],
                 on_toggle: Callable[[], None],
                 on_emergency: Callable[[], None]):
        self._be = backend
        self._on_preset = on_preset
        self._on_toggle = on_toggle
        self._on_emergency = on_emergency
        self._prev: dict[int, bool] = {vk: False for vk in WATCHED}
        self.enabled = True

    def _modifier_held(self) -> bool:
        return any(self._be.key_down(m) for m in MODIFIER_KEYS)

    def poll(self) -> None:
        be = self._be
        for vk in WATCHED:
            down = be.key_down(vk)
            rising = down and not self._prev[vk]
            self._prev[vk] = down
            if not rising:
                continue
            if vk == VK_F9:
                self._on_emergency()          # always active (safety)
                continue
            if not self.enabled or self._modifier_held():
                continue
            if vk == VK_F8:
                self._on_toggle()
            else:
                self._on_preset(PRESET_KEYS[vk])
