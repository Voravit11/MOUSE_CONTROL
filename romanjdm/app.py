# -*- coding: utf-8 -*-
"""Program start-up: single instance, local data, engine, GUI, safe shutdown.

`--selftest [--selftest-out FILE]` runs a headless check (used by build.bat on
the freshly built EXE): data folder in a temp dir, engine with a fake mouse,
GUI built off-screen, F1-F4 preset switching, Arabic-numerals check, clean
shutdown. It never touches the real mouse or the real user data.
"""
from __future__ import annotations

import atexit
import json
import os
import sys
import tempfile
import threading
import traceback

from .version import APP_NAME, APP_VERSION


def _install_excepthook(store_getter) -> None:
    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        store = store_getter()
        if store is not None:
            store.log_error(text)
    sys.excepthook = hook

    def thread_hook(args):
        hook(args.exc_type, args.exc_value, args.exc_traceback)
    threading.excepthook = thread_hook


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in args:
        out = args[args.index("--selftest-out") + 1] if "--selftest-out" in args else None
        return run_selftest(out)

    from .winapi import IS_WINDOWS, acquire_single_instance
    from PySide6.QtCore import QLocale
    from PySide6.QtWidgets import QApplication, QMessageBox
    from .engine import MouseEngine
    from .gui import ARABIC_LOCALE, STYLE, MainWindow
    from .storage import DataStore

    holder = {"store": None}
    _install_excepthook(lambda: holder["store"])

    app = QApplication(sys.argv)
    if not IS_WINDOWS:
        QMessageBox.critical(None, APP_NAME, f"{APP_NAME} only runs on Windows 10/11.")
        return 1
    QLocale.setDefault(ARABIC_LOCALE)
    app.setStyleSheet(STYLE)
    if not acquire_single_instance():
        QMessageBox.warning(None, APP_NAME, f"{APP_NAME} is already running.")
        return 0

    store = DataStore()
    holder["store"] = store
    engine = MouseEngine(store.config["settings"])
    atexit.register(engine.shutdown)             # safety net on abnormal exit
    engine.start()
    win = MainWindow(store, engine)
    app.aboutToQuit.connect(engine.shutdown)
    win.show()
    code = app.exec()
    engine.shutdown()
    return code


def run_selftest(out_path: str | None) -> int:
    result = {"version": APP_VERSION, "checks": {}, "ok": False}

    def check(name: str, cond: bool) -> None:
        result["checks"][name] = bool(cond)

    try:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        tmp = tempfile.mkdtemp(prefix="romanjdm_selftest_")
        os.environ["ROMANJDM_DATA_DIR"] = tmp

        from PySide6.QtWidgets import QApplication
        from .engine import MouseEngine
        from .gui import ARABIC_LOCALE, STYLE, MainWindow, find_non_ascii_digits
        from .storage import DataStore
        from .testing import FakeBackend
        from .winapi import VK_F2, VK_LBUTTON, VK_RBUTTON
        from PySide6.QtCore import QLocale

        QLocale.setDefault(ARABIC_LOCALE)
        qapp = QApplication.instance() or QApplication([])
        qapp.setStyleSheet(STYLE)

        store = DataStore()
        check("first_run_creates_files", all((store.dir / n).exists() for n in
                                             ("config.json", "presets.json", "user_settings.json")))
        check("four_presets", len(store.presets["presets"]) == 4)

        be = FakeBackend(simulated=True)
        engine = MouseEngine(store.config["settings"], be)
        engine._quit.set()      # stepped by hand below: the GUI watchdog must not start a thread
        win = MainWindow(store, engine)
        win.show()

        # engine: continuous movement without real input
        win.c_x.set_value(30)
        win.c_y.set_value(60)
        win._on_changed()
        engine.arm()
        be.press(VK_LBUTTON, VK_RBUTTON)
        end = be.t + 1.0
        while be.t < end:
            be.sleep(engine.step(be.now()))
        dx, dy = be.total()
        check("continuous_movement", abs(dx - 100) <= 3 and abs(dy - 200) <= 3)
        be.release(VK_RBUTTON)
        n = len(be.moves)
        engine.step(be.now())
        check("stops_on_release", len(be.moves) == n and not engine.moving)

        # F2 hotkey -> preset 2 becomes active in the GUI
        be.press(VK_F2)
        engine.step(be.now())
        be.release(VK_F2)
        win._refresh()
        check("hotkey_switches_preset", win.presets.active == 2)

        check("arabic_numerals_only", not find_non_ascii_digits(win))

        win.close()
        qapp.processEvents()

        # real worker thread with a fake mouse: starts once, stops cleanly
        be2 = FakeBackend(simulated=False)
        eng2 = MouseEngine({"x": 0, "y": 50, "duration": 100}, be2)
        eng2.start()
        eng2.start()
        check("single_engine_thread",
              sum(1 for t in threading.enumerate() if t.name == "MouseEngine") == 1)
        eng2.arm()
        be2.press(VK_LBUTTON, VK_RBUTTON)
        threading.Event().wait(0.3)
        be2.release(VK_LBUTTON)
        threading.Event().wait(0.05)
        check("thread_moves_then_stops", be2.total()[1] > 0)
        eng2.shutdown()
        check("no_engine_thread_left",
              not any(t.name == "MouseEngine" and t.is_alive() for t in threading.enumerate()))
        result["ok"] = all(result["checks"].values())
    except Exception:
        result["error"] = traceback.format_exc()
    path = out_path or os.path.join(tempfile.gettempdir(), "romanjdm_selftest.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
    except OSError:
        pass
    return 0 if result["ok"] else 1
