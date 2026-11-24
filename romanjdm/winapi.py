# -*- coding: utf-8 -*-
"""Thin Windows API layer (ctypes). Importable on any OS; only usable on Windows.

Design rules (unchanged from V1):
* Only RELATIVE mouse movement is injected (SendInput + MOUSEEVENTF_MOVE).
* The program never presses or releases mouse buttons.
* Button / key state is read by polling GetAsyncKeyState (no global hooks).
"""
from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes

IS_WINDOWS = sys.platform == "win32"

VK_LBUTTON = 0x01
VK_RBUTTON = 0x02
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12      # Alt
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_F1 = 0x70
VK_F2 = 0x71
VK_F3 = 0x72
VK_F4 = 0x73
VK_F8 = 0x77        # Start / Stop toggle
VK_F9 = 0x78        # EMERGENCY STOP

INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
SIGNATURE = 0x524F4D41  # "ROMA" - dwExtraInfo tag on injected events


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG), ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32 = kernel32 = winmm = None
if IS_WINDOWS:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    winmm = ctypes.WinDLL("winmm")
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    winmm.timeBeginPeriod.argtypes = [wintypes.UINT]
    winmm.timeEndPeriod.argtypes = [wintypes.UINT]


class WinBackend:
    """Real backend used by the engine on Windows."""

    def key_down(self, vk: int) -> bool:
        """True if the key / mouse button is physically down right now."""
        return bool(user32.GetAsyncKeyState(vk) & 0x8000)

    def send_move(self, dx: int, dy: int) -> bool:
        """Inject a relative mouse move. Returns False if Windows rejected it."""
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.u.mi = MOUSEINPUT(int(dx), int(dy), 0, MOUSEEVENTF_MOVE, 0, SIGNATURE)
        return user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) == 1

    @staticmethod
    def now() -> float:
        return time.perf_counter()

    @staticmethod
    def sleep(seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)

    @staticmethod
    def begin_timer() -> None:
        winmm.timeBeginPeriod(1)

    @staticmethod
    def end_timer() -> None:
        winmm.timeEndPeriod(1)


_mutex_handle = None


def acquire_single_instance(name: str = "Local\\ROMANJDM_MOUSE_CONTROL_SINGLETON") -> bool:
    """Only one copy of the program may run (prevents duplicated engines)."""
    global _mutex_handle
    if not IS_WINDOWS:
        return True
    _mutex_handle = kernel32.CreateMutexW(None, False, name)
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS
