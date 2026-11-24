# -*- coding: utf-8 -*-
"""ROMANJDM GUI (PySide6). Dark gaming style, cyan accent.

All numbers shown anywhere in this GUI are ASCII digits 0-9 (never Thai or
other numerals): spin boxes use an explicit English locale and every other
number is produced with Python f-strings.
"""
from __future__ import annotations

import math
import os
import threading

from PySide6.QtCore import QLocale, QObject, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFrame, QGridLayout,
    QGroupBox, QHBoxLayout, QInputDialog, QLabel, QMainWindow, QMessageBox,
    QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from . import updater
from .engine import (
    MouseEngine, STATE_ACTIVE, STATE_ARMED, STATE_EMERGENCY, STATE_STOPPED,
)
from .presets import PresetManager
from .settings import (
    DEFAULTS, EASING_LABELS, EASINGS, LIMITS, PRESET_COUNT, PRESET_NAME_MAX,
    effective_duration_ms, ease, sanitize,
)
from .storage import DataStore
from .version import APP_NAME, APP_VERSION, updates_configured

ACCENT = "#00e5ff"
RED = "#ff4d6a"
AMBER = "#ffb020"
GREEN = "#2ee6a6"
MUTED = "#6b7a88"

STATE_COLORS = {
    STATE_STOPPED: RED,
    STATE_ARMED: AMBER,
    STATE_ACTIVE: ACCENT,
    STATE_EMERGENCY: "#ff1744",
}

STYLE = f"""
QWidget {{ background: #07090c; color: #d7dde3; font-family: 'Segoe UI'; font-size: 10pt; }}
QMainWindow, QDialog {{ background: #07090c; }}
QLabel, QCheckBox {{ background: transparent; }}
QGroupBox {{ background: #11151a; border: 1px solid #1f2933; border-radius: 8px;
             margin-top: 14px; padding: 14px 10px 8px 10px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; color: {ACCENT}; }}
QFrame#card {{ background: #11151a; border: 1px solid #1f2933; border-radius: 8px; }}
QFrame#card[active="true"] {{ border: 2px solid {ACCENT}; }}
QSpinBox, QDoubleSpinBox, QComboBox {{ background: #07090c; border: 1px solid #2a3642; border-radius: 4px;
             padding: 3px 6px; color: {ACCENT}; selection-background-color: {ACCENT}; selection-color: #000; }}
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border: 1px solid {ACCENT}; }}
QComboBox QAbstractItemView {{ background: #11151a; selection-background-color: {ACCENT}; selection-color: #000; }}
QSlider::groove:horizontal {{ height: 5px; background: #222c36; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {ACCENT}; width: 14px; margin: -6px 0; border-radius: 7px; }}
QPushButton {{ background: #1a222b; border: 1px solid #2a3642; border-radius: 5px; padding: 6px 12px; font-weight: 600; }}
QPushButton:hover {{ border: 1px solid {ACCENT}; color: {ACCENT}; }}
QPushButton:disabled {{ color: #566370; border: 1px solid #1f2933; }}
QPushButton#start {{ background: {ACCENT}; color: #001418; border: none; }}
QPushButton#start:disabled {{ background: #123840; color: #3c6872; }}
QPushButton#stop {{ background: #2a1318; color: {RED}; border: 1px solid #5a2430; }}
QPushButton#emergency {{ background: #b3122d; color: white; border: none; }}
QPushButton#emergency:hover {{ background: #e0183a; color: white; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid #2a3642; border-radius: 3px; background: #07090c; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; }}
QLabel#title {{ font-size: 17pt; font-weight: 800; color: {ACCENT}; letter-spacing: 2px; }}
QLabel#sub {{ color: {MUTED}; }}
QLabel#badge {{ border-radius: 4px; padding: 2px 8px; font-weight: 700; font-size: 8pt; background: #1a222b; color: {MUTED}; }}
"""

ARABIC_LOCALE = QLocale(QLocale.Language.English, QLocale.Country.UnitedStates)

# Numeral blocks that must never appear in the GUI (Thai, Arabic-Indic, Extended Arabic-Indic).
_FORBIDDEN_DIGITS = [(0x0E50, 0x0E59), (0x0660, 0x0669), (0x06F0, 0x06F9)]


def has_non_ascii_digits(text: str) -> bool:
    return any(lo <= ord(ch) <= hi for ch in text for lo, hi in _FORBIDDEN_DIGITS)


def find_non_ascii_digits(root: QWidget) -> list[str]:
    """Return texts of all child widgets that contain non-Arabic numerals (selftest)."""
    bad = []
    for w in [root] + root.findChildren(QWidget):
        texts = []
        for attr in ("text", "title", "windowTitle", "toolTip", "suffix", "currentText"):
            fn = getattr(w, attr, None)
            if callable(fn):
                try:
                    texts.append(str(fn()))
                except Exception:
                    pass
        bad.extend(t for t in texts if has_non_ascii_digits(t))
    return bad


# --------------------------------------------------------------------- widgets
class ParamControl(QWidget):
    """Title + numeric box + slider kept in sync. Emits changed()."""
    changed = Signal()

    def __init__(self, title: str, lo: float, hi: float, decimals: int = 0, suffix: str = ""):
        super().__init__()
        self._scale = 10 ** decimals
        self._busy = False
        if decimals:
            self.spin = QDoubleSpinBox()
            self.spin.setDecimals(decimals)
            self.spin.setSingleStep(1.0 / self._scale)
        else:
            self.spin = QSpinBox()
            self.spin.setSingleStep(1)
        self.spin.setLocale(ARABIC_LOCALE)
        self.spin.setGroupSeparatorShown(False)
        self.spin.setRange(lo, hi)
        self.spin.setSuffix(suffix)
        self.spin.setMinimumWidth(110)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(int(round(lo * self._scale)), int(round(hi * self._scale)))
        lay = QGridLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.addWidget(QLabel(title), 0, 0)
        lay.addWidget(self.spin, 0, 1)
        lay.addWidget(self.slider, 1, 0, 1, 2)
        lay.setColumnStretch(0, 1)
        self.spin.valueChanged.connect(self._from_spin)
        self.slider.valueChanged.connect(self._from_slider)

    def _from_spin(self, v) -> None:
        if self._busy:
            return
        self._busy = True
        self.slider.setValue(int(round(v * self._scale)))
        self._busy = False
        self.changed.emit()

    def _from_slider(self, v: int) -> None:
        if self._busy:
            return
        self._busy = True
        self.spin.setValue(v / self._scale if self._scale > 1 else v)
        self._busy = False
        self.changed.emit()

    def value(self):
        return self.spin.value()

    def set_value(self, v) -> None:
        self._busy = True
        self.spin.setValue(v)
        self.slider.setValue(int(round(v * self._scale)))
        self._busy = False


class PreviewWidget(QWidget):
    """Direction of the movement and the start-up (easing) profile."""

    def __init__(self):
        super().__init__()
        self.setMinimumSize(220, 220)
        self._x = self._y = 0
        self._mode = "linear"
        self._active = False

    def set_params(self, x: int, y: int, mode: str) -> None:
        self._x, self._y, self._mode = x, y, mode
        self.update()

    def set_active(self, active: bool) -> None:
        if active != self._active:
            self._active = active
            self.update()

    def paintEvent(self, _event) -> None:
        pt = QPainter(self)
        pt.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        pt.fillRect(self.rect(), QColor("#07090c"))
        cx, cy = w / 2, h / 2
        radius = max(10.0, min(w, h) / 2 - 24)
        pt.setPen(QPen(QColor("#18222c"), 1))
        for i in range(1, 5):
            r = radius * i / 4
            pt.drawEllipse(QPointF(cx, cy), r, r)
        pt.drawLine(QPointF(cx - radius, cy), QPointF(cx + radius, cy))
        pt.drawLine(QPointF(cx, cy - radius), QPointF(cx, cy + radius))
        pt.setPen(QColor("#4b5a68"))
        pt.setFont(QFont("Segoe UI", 8))
        pt.drawText(int(cx + radius - 14), int(cy - 6), "+X")
        pt.drawText(int(cx - radius + 2), int(cy - 6), "-X")
        pt.drawText(int(cx + 6), int(cy + radius + 12), "+Y (down)")
        pt.drawText(int(cx + 6), int(cy - radius + 2), "-Y (up)")
        m = max(abs(self._x), abs(self._y))
        if m == 0:
            pt.setPen(QColor(MUTED))
            pt.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "NO MOVEMENT")
            return
        sc = radius / m
        ex, ey = cx + self._x * sc, cy + self._y * sc
        color = QColor("#ffffff") if self._active else QColor(ACCENT)
        pt.setPen(QPen(QColor(0, 229, 255, 90), 2))
        pt.drawLine(QPointF(cx, cy), QPointF(ex, ey))
        pt.setPen(Qt.PenStyle.NoPen)
        pt.setBrush(color)
        n = 20
        for i in range(n + 1):          # dot spacing = start-up ramp profile
            e = ease(i / n, self._mode)
            pt.drawEllipse(QPointF(cx + self._x * sc * e, cy + self._y * sc * e), 2.4, 2.4)
        ang = math.atan2(ey - cy, ex - cx)
        size = 12
        pt.drawPolygon(QPolygonF([
            QPointF(ex, ey),
            QPointF(ex - size * math.cos(ang - 0.4), ey - size * math.sin(ang - 0.4)),
            QPointF(ex - size * math.cos(ang + 0.4), ey - size * math.sin(ang + 0.4)),
        ]))
        pt.setBrush(QColor("#ffffff"))
        pt.drawEllipse(QPointF(cx, cy), 3.5, 3.5)


def _summary(s: dict) -> str:
    return (f"X: {s['x']}   Y: {s['y']}\n"
            f"Duration: {s['duration']} ms   Speed: {s['speed']:.1f}\n"
            f"Smoothness: {s['smoothness']}   {EASING_LABELS[s['easing']].split(' (')[0]}")


class PresetCard(QFrame):
    save_clicked = Signal(int)
    load_clicked = Signal(int)
    rename_clicked = Signal(int)
    reset_clicked = Signal(int)

    def __init__(self, n: int):
        super().__init__()
        self.n = n
        self.setObjectName("card")
        self.setProperty("active", False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        head = QHBoxLayout()
        self.lbl_title = QLabel(f"PRESET {n}")
        self.lbl_title.setStyleSheet(f"font-weight:800; color:{ACCENT};")
        self.lbl_key = QLabel(f"F{n}")
        self.lbl_key.setObjectName("badge")
        head.addWidget(self.lbl_title)
        head.addStretch(1)
        head.addWidget(self.lbl_key)
        lay.addLayout(head)
        self.lbl_name = QLabel()
        self.lbl_name.setStyleSheet("font-size:11pt; font-weight:600;")
        lay.addWidget(self.lbl_name)
        badges = QHBoxLayout()
        self.lbl_active = QLabel("ACTIVE")
        self.lbl_active.setObjectName("badge")
        self.lbl_state = QLabel("EMPTY")
        self.lbl_state.setObjectName("badge")
        badges.addWidget(self.lbl_active)
        badges.addWidget(self.lbl_state)
        badges.addStretch(1)
        lay.addLayout(badges)
        self.lbl_values = QLabel()
        self.lbl_values.setFont(QFont("Consolas", 8))
        self.lbl_values.setStyleSheet(f"color:{MUTED};")
        lay.addWidget(self.lbl_values)
        row = QGridLayout()
        specs = (("Save", self.save_clicked), ("Load", self.load_clicked),
                 ("Edit Name", self.rename_clicked), ("Reset", self.reset_clicked))
        for i, (text, sig) in enumerate(specs):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, s=sig: s.emit(self.n))
            row.addWidget(b, i // 2, i % 2)
        lay.addLayout(row)

    def refresh(self, slot: dict, active: bool, modified: bool) -> None:
        self.lbl_name.setText(slot["name"])
        saved = slot["saved"]
        self.lbl_state.setText("SAVED" if saved else "EMPTY")
        self.lbl_state.setStyleSheet(f"color:{GREEN if saved else MUTED};")
        self.lbl_active.setVisible(active)
        self.lbl_active.setText("ACTIVE + MODIFIED" if (active and modified) else "ACTIVE")
        self.lbl_active.setStyleSheet(f"color:{ACCENT};")
        self.lbl_values.setText(_summary(slot["settings"]))
        self.setProperty("active", active)
        self.style().unpolish(self)
        self.style().polish(self)


class UpdateWorker(QObject):
    """Runs network work on a short-lived helper thread; reports via signals."""
    checked = Signal(object)          # ReleaseInfo
    downloaded = Signal(object, str)  # ReleaseInfo, signature status
    failed = Signal(str)
    progress = Signal(int, int)

    def __init__(self):
        super().__init__()
        self.busy = False

    def _spawn(self, fn, *args) -> None:
        if self.busy:
            return
        self.busy = True

        def run():
            try:
                fn(*args)
            except updater.UpdateError as exc:
                self.failed.emit(str(exc))
            except Exception as exc:
                self.failed.emit(f"Unexpected error: {exc}")
            finally:
                self.busy = False

        threading.Thread(target=run, name="UpdateWorker", daemon=True).start()

    def check(self) -> None:
        self._spawn(lambda: self.checked.emit(updater.fetch_latest_release()))

    def download(self, rel) -> None:
        def job():
            folder = updater.target_folder()
            dest = folder / rel.exe_name
            updater.download_file(rel.exe_url, dest, lambda d, t: self.progress.emit(d, t))
            try:
                updater.verify_sha256(dest, updater.download_text(rel.sums_url), rel.exe_name)
                status = updater.authenticode_status(dest)
                if not updater.signature_allows_install(status):
                    raise updater.UpdateError(f"Digital signature check failed ({status})")
            except Exception:
                dest.unlink(missing_ok=True)       # never keep an unverified file
                raise
            self.downloaded.emit(rel, f"{dest}|{status}")
        self._spawn(job)


# ----------------------------------------------------------------- main window
class MainWindow(QMainWindow):
    def __init__(self, store: DataStore, engine: MouseEngine):
        super().__init__()
        self.store = store
        self.engine = engine
        self.presets = PresetManager(store)
        self.worker = UpdateWorker()
        self.worker.checked.connect(self._on_update_checked)
        self.worker.downloaded.connect(self._on_update_downloaded)
        self.worker.failed.connect(self._on_update_failed)
        self.setWindowTitle(f"{APP_NAME}  v{APP_VERSION}")
        self.setMinimumSize(900, 720)
        self._build_ui()
        self._load_values_into_ui(self.presets.working)
        self.chk_hotkeys.setChecked(store.user["hotkeys_enabled"])
        self.engine.set_hotkeys_enabled(store.user["hotkeys_enabled"])
        self._refresh_cards()
        for w in store.warnings:
            self._log(w)
        if store.migrated_from_v1:
            self._log("Settings and presets were imported from V1 (the V1 file was not changed)")
        self._save_timer = QTimer(self)             # debounced auto-save of working values
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(800)
        self._save_timer.timeout.connect(self._autosave)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(33)

    # ---- construction -------------------------------------------------------
    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(16, 12, 16, 12)

        top = QHBoxLayout()
        title_col = QVBoxLayout()
        title = QLabel(APP_NAME)
        title.setObjectName("title")
        sub = QLabel("Hold LEFT + RIGHT mouse = run  |  release either = stop  |  "
                     "F1-F4: presets  |  F8: Start/Stop  |  F9: EMERGENCY STOP")
        sub.setObjectName("sub")
        title_col.addWidget(title)
        title_col.addWidget(sub)
        top.addLayout(title_col, 1)
        self.lbl_status = QLabel(STATE_STOPPED)
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_status.setMinimumWidth(210)
        self.lbl_status.setMinimumHeight(46)
        top.addWidget(self.lbl_status)
        outer.addLayout(top)

        body = QHBoxLayout()
        outer.addLayout(body, 1)

        box = QGroupBox("MOVEMENT SETTINGS")
        bl = QVBoxLayout(box)
        self.c_x = ParamControl("X Axis (- left, + right)", *LIMITS["x"])
        self.c_y = ParamControl("Y Axis (- up, + down)", *LIMITS["y"])
        self.c_dur = ParamControl("Duration", *LIMITS["duration"], suffix=" ms")
        self.c_speed = ParamControl("Speed (multiplier)", *LIMITS["speed"], decimals=1, suffix=" x")
        self.c_smooth = ParamControl("Smoothness (update rate)", *LIMITS["smoothness"])
        for c in (self.c_x, self.c_y, self.c_dur, self.c_speed, self.c_smooth):
            bl.addWidget(c)
            c.changed.connect(self._on_changed)
        row = QHBoxLayout()
        row.addWidget(QLabel("Easing (start-up)"))
        self.cb_easing = QComboBox()
        for k in EASINGS:
            self.cb_easing.addItem(EASING_LABELS[k], k)
        self.cb_easing.currentIndexChanged.connect(self._on_changed)
        row.addWidget(self.cb_easing, 1)
        bl.addLayout(row)
        body.addWidget(box, 5)

        right = QVBoxLayout()
        body.addLayout(right, 4)
        dash = QGroupBox("DASHBOARD")
        dl = QVBoxLayout(dash)
        self.lbl_active_preset = QLabel()
        self.lbl_active_preset.setStyleSheet(f"font-size:12pt; font-weight:700; color:{ACCENT};")
        self.lbl_buttons = QLabel()
        self.lbl_buttons.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_values = QLabel()
        self.lbl_values.setFont(QFont("Consolas", 10))
        self.lbl_hotkey_state = QLabel()
        self.lbl_hotkey_state.setObjectName("sub")
        for w in (self.lbl_active_preset, self.lbl_buttons, self.lbl_values, self.lbl_hotkey_state):
            dl.addWidget(w)
        right.addWidget(dash)
        pbox = QGroupBox("PREVIEW")
        pl = QVBoxLayout(pbox)
        self.preview = PreviewWidget()
        pl.addWidget(self.preview)
        right.addWidget(pbox, 1)

        cards = QGroupBox("PRESETS")
        cl = QHBoxLayout(cards)
        self.cards: list[PresetCard] = []
        for n in range(1, PRESET_COUNT + 1):
            c = PresetCard(n)
            c.save_clicked.connect(self._save_preset)
            c.load_clicked.connect(lambda n_: self._activate_preset(n_, "Load button"))
            c.rename_clicked.connect(self._rename_preset)
            c.reset_clicked.connect(self._reset_preset)
            cl.addWidget(c, 1)
            self.cards.append(c)
        outer.addWidget(cards)

        bottom = QHBoxLayout()
        self.btn_start = QPushButton("START")
        self.btn_start.setObjectName("start")
        self.btn_stop = QPushButton("STOP")
        self.btn_stop.setObjectName("stop")
        self.btn_defaults = QPushButton("Default Values")
        self.btn_emergency = QPushButton("EMERGENCY STOP (F9)")
        self.btn_emergency.setObjectName("emergency")
        self.btn_start.clicked.connect(self.engine.arm)
        self.btn_stop.clicked.connect(lambda: self.engine.disarm("Stopped"))
        self.btn_defaults.clicked.connect(self._defaults)
        self.btn_emergency.clicked.connect(lambda: self.engine.emergency_stop("button"))
        self.chk_hotkeys = QCheckBox("Global hotkeys (F1-F4, F8)")
        self.chk_hotkeys.toggled.connect(self._on_hotkeys_toggled)
        self.btn_folder = QPushButton("Open Data Folder")
        self.btn_folder.clicked.connect(self._open_data_folder)
        self.btn_update = QPushButton("Check for Updates")
        self.btn_update.clicked.connect(self._check_updates)
        for b in (self.btn_start, self.btn_stop, self.btn_defaults):
            bottom.addWidget(b)
        bottom.addSpacing(12)
        bottom.addWidget(self.chk_hotkeys)
        bottom.addStretch(1)
        bottom.addWidget(self.btn_folder)
        bottom.addWidget(self.btn_update)
        bottom.addWidget(self.btn_emergency)
        outer.addLayout(bottom)

        foot = QHBoxLayout()
        self.lbl_log = QLabel("Ready")
        self.lbl_log.setObjectName("sub")
        lbl_ver = QLabel(f"Version {APP_VERSION}")
        lbl_ver.setObjectName("sub")
        foot.addWidget(self.lbl_log, 1)
        foot.addWidget(lbl_ver)
        outer.addLayout(foot)

    # ---- settings <-> UI ------------------------------------------------------
    def _ui_settings(self) -> dict:
        return sanitize({
            "x": self.c_x.value(), "y": self.c_y.value(),
            "duration": self.c_dur.value(), "smoothness": self.c_smooth.value(),
            "speed": self.c_speed.value(), "easing": self.cb_easing.currentData(),
        })

    def _load_values_into_ui(self, s: dict) -> None:
        s = sanitize(s)
        widgets = (self.c_x, self.c_y, self.c_dur, self.c_smooth, self.c_speed, self.cb_easing)
        for w in widgets:
            w.blockSignals(True)
        self.c_x.set_value(s["x"])
        self.c_y.set_value(s["y"])
        self.c_dur.set_value(s["duration"])
        self.c_smooth.set_value(s["smoothness"])
        self.c_speed.set_value(s["speed"])
        self.cb_easing.setCurrentIndex(max(0, self.cb_easing.findData(s["easing"])))
        for w in widgets:
            w.blockSignals(False)
        self._apply_working(s, user_edit=False)

    def _apply_working(self, s: dict, user_edit: bool) -> None:
        self.engine.update_settings(s)
        if user_edit:
            self.presets.edit(s)
            self._save_timer.start()
        eff = effective_duration_ms(s["duration"], s["speed"])
        self.lbl_values.setText(
            f"X: {s['x']}   Y: {s['y']}\n"
            f"Duration: {s['duration']} ms  (effective {eff:.0f} ms at {s['speed']:.1f} x)\n"
            f"Smoothness: {s['smoothness']}   Easing: {EASING_LABELS[s['easing']]}")
        self.preview.set_params(s["x"], s["y"], s["easing"])
        self._refresh_cards()

    def _on_changed(self, *_args) -> None:
        self._apply_working(self._ui_settings(), user_edit=True)

    def _autosave(self) -> None:
        self.presets.flush()

    def _defaults(self) -> None:
        self._load_values_into_ui(DEFAULTS)
        self._on_changed()
        self._log("Values set to defaults (presets not changed)")

    # ---- presets ----------------------------------------------------------------
    def _refresh_cards(self) -> None:
        pm = self.presets
        for c in self.cards:
            c.refresh(pm.slot(c.n), c.n == pm.active, pm.modified and c.n == pm.active)
        slot = pm.slot(pm.active)
        self.lbl_active_preset.setText(
            f"Active Preset: {pm.active} - {slot['name']}" + ("  (modified)" if pm.modified else ""))

    def _activate_preset(self, n: int, source: str) -> None:
        s = self.presets.activate(n)
        self._load_values_into_ui(s)
        slot = self.presets.slot(n)
        note = "" if slot["saved"] else " (empty - default values)"
        self._log(f"Preset {n} active: {slot['name']}{note}  [{source}]")

    def _save_preset(self, n: int) -> None:
        slot = self.presets.slot(n)
        if slot["saved"]:
            ans = QMessageBox.question(self, "Save Preset",
                                       f"Overwrite Preset {n} ({slot['name']}) with the current values?")
            if ans != QMessageBox.StandardButton.Yes:
                return
        self.presets.save(n, self._ui_settings())
        self._refresh_cards()
        self._log(f"Preset {n} saved")

    def _rename_preset(self, n: int) -> None:
        name, ok = QInputDialog.getText(self, "Edit Name", f"Name for Preset {n} (max {PRESET_NAME_MAX}):",
                                        text=self.presets.slot(n)["name"])
        if ok:
            final = self.presets.rename(n, name)
            self._refresh_cards()
            self._log(f"Preset {n} renamed to '{final}'")

    def _reset_preset(self, n: int) -> None:
        ans = QMessageBox.question(self, "Reset Preset",
                                   f"Reset Preset {n} to empty? A backup copy is kept in the backups folder.")
        if ans != QMessageBox.StandardButton.Yes:
            return
        was_active = n == self.presets.active
        self.presets.reset(n)
        if was_active:
            self._load_values_into_ui(self.presets.working)
        self._refresh_cards()
        self._log(f"Preset {n} reset")

    # ---- misc controls -------------------------------------------------------------
    def _on_hotkeys_toggled(self, on: bool) -> None:
        self.engine.set_hotkeys_enabled(on)
        self.store.user["hotkeys_enabled"] = bool(on)
        self.store.save_user()
        self._log("Global hotkeys " + ("ON (F9 always active)" if on else "OFF (only F9 EMERGENCY STOP works)"))

    def _open_data_folder(self) -> None:
        try:
            self.store.dir.mkdir(parents=True, exist_ok=True)
            os.startfile(str(self.store.dir))          # Windows only
        except Exception as exc:
            self._log(f"Could not open folder: {exc}")

    # ---- updates (optional, always user-confirmed) ------------------------------------
    def _check_updates(self) -> None:
        if not updates_configured():
            QMessageBox.information(self, "Updates", "Update checking is not configured in this build.\n"
                                    "Download new versions manually from the GitHub Releases page.")
            return
        if self.worker.busy:
            return
        self.btn_update.setEnabled(False)
        self._log("Checking GitHub Releases ...")
        self.worker.check()

    def _on_update_checked(self, rel) -> None:
        self.btn_update.setEnabled(True)
        if not updater.is_newer(rel.version):
            self._log(f"You have the latest version ({APP_VERSION})")
            QMessageBox.information(self, "Updates", f"You are up to date (version {APP_VERSION}).")
            return
        ans = QMessageBox.question(
            self, "Update available",
            f"Version {rel.version} is available (you have {APP_VERSION}).\n\n"
            f"The new EXE will be downloaded, verified with SHA-256 and saved next to this program "
            f"under its own name. Your current EXE and all your presets stay untouched.\n\nDownload now?")
        if ans == QMessageBox.StandardButton.Yes:
            self.btn_update.setEnabled(False)
            self._log(f"Downloading {rel.exe_name} ...")
            self.worker.download(rel)
        else:
            self._log("Update skipped")

    def _on_update_downloaded(self, rel, info: str) -> None:
        self.btn_update.setEnabled(True)
        path, status = info.rsplit("|", 1)
        sig = ("digitally signed (valid)" if status == "Valid"
               else "NOT digitally signed (SHA-256 verified only)" if status == "NotSigned"
               else "signature status unknown (SHA-256 verified)")
        self._log(f"Update {rel.version} verified")
        QMessageBox.information(
            self, "Update downloaded",
            f"Version {rel.version} was downloaded and its SHA-256 matches the release.\n"
            f"The file is {sig}.\n\nSaved as:\n{path}\n\n"
            f"Close this program and open the new file. Keep the old EXE until you are happy "
            f"with the new one (rollback).")

    def _on_update_failed(self, text: str) -> None:
        self.btn_update.setEnabled(True)
        self._log(f"Update: {text}")

    # ---- periodic refresh ----------------------------------------------------------------
    def _log(self, text: str) -> None:
        self.lbl_log.setText(text)

    def _refresh(self) -> None:
        eng = self.engine
        if not eng.is_alive():
            eng.start()                              # no-op unless the thread really died
        while eng.events:
            kind, payload = eng.events.popleft()
            if kind == "message":
                self._log(payload)
            elif kind == "preset":
                self._activate_preset(payload, f"hotkey F{payload}")
        state = eng.state
        color = STATE_COLORS[state]
        self.lbl_status.setText(state)
        self.lbl_status.setStyleSheet(
            f"font-size:17pt; font-weight:800; color:{color}; border:2px solid {color}; border-radius:8px;")
        self.btn_start.setEnabled(state in (STATE_STOPPED, STATE_EMERGENCY))
        self.btn_stop.setEnabled(state in (STATE_ARMED, STATE_ACTIVE))
        lc = ACCENT if eng.left_down else "#3a4652"
        rc = ACCENT if eng.right_down else "#3a4652"
        self.lbl_buttons.setText(
            f"<span style='color:{lc}'>[ LEFT MOUSE ]</span>  +  <span style='color:{rc}'>[ RIGHT MOUSE ]</span>")
        self.lbl_hotkey_state.setText(
            "Global hotkeys: ON" if self.chk_hotkeys.isChecked() else "Global hotkeys: OFF (F9 still works)")
        self.preview.set_active(state == STATE_ACTIVE)

    # ---- shutdown -----------------------------------------------------------------------------
    def closeEvent(self, event) -> None:
        try:
            self._timer.stop()
            self.engine.shutdown()
        finally:
            try:
                self.presets.flush()
            except Exception as exc:
                self.store.log_error(f"flush on close failed: {exc!r}")
        event.accept()
