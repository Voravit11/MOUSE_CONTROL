# -*- coding: utf-8 -*-
"""Local user data (never uploaded anywhere).

%LOCALAPPDATA%\\ROMANJDM\\
    config.json         working movement values + active preset number
    presets.json        the 4 preset slots
    user_settings.json  UI options (global hotkeys on/off ...)
    backups/            timestamped copies made before a file changes
    error.log           local crash / error log (only if something fails)

Rules
-----
* Files are only written when the content really changes (no pointless
  rewrites) and always atomically (temp file + os.replace).
* Before an existing file is changed, a copy goes to backups/ (at most once per
  session for routine auto-saves, always for destructive actions).
* A corrupt file is moved to backups/ and the newest valid backup is restored;
  only if there is none do defaults get created.
* An update of the EXE never touches this folder.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

from .settings import PRESET_COUNT, PRESET_NAME_MAX, sanitize

SCHEMA_VERSION = 2
BACKUP_KEEP = 10
FILES = ("config.json", "presets.json", "user_settings.json")


# ------------------------------------------------------------------ locations
def default_data_dir() -> Path:
    override = os.environ.get("ROMANJDM_DATA_DIR")      # developer / test override
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        base = str(Path.home() / "AppData" / "Local")
    return Path(base) / "ROMANJDM"


def legacy_v1_paths() -> list[Path]:
    """Where V1 may have stored its config.json (read-only, for migration)."""
    paths = []
    if getattr(sys, "frozen", False):
        paths.append(Path(sys.executable).resolve().parent / "config.json")
    else:
        paths.append(Path(__file__).resolve().parent.parent / "config.json")
    appdata = os.environ.get("APPDATA")
    if appdata:
        paths.append(Path(appdata) / "ROMANJDM_MOUSE_CONTROL" / "config.json")
    return paths


# ----------------------------------------------------------------- validation
def clean_name(raw, fallback: str) -> str:
    if not isinstance(raw, str):
        return fallback
    name = " ".join(raw.split())[:PRESET_NAME_MAX].strip()
    return name or fallback


def default_slot(n: int) -> dict:
    return {"slot": n, "name": f"Preset {n}", "saved": False, "settings": sanitize({})}


def validate_presets(raw) -> list[dict]:
    """Always returns exactly PRESET_COUNT valid slots."""
    items = raw.get("presets") if isinstance(raw, dict) else raw
    items = items if isinstance(items, list) else []
    slots = []
    for i in range(PRESET_COUNT):
        n = i + 1
        item = items[i] if i < len(items) and isinstance(items[i], dict) else {}
        slots.append({
            "slot": n,
            "name": clean_name(item.get("name"), f"Preset {n}"),
            "saved": bool(item.get("saved")) if isinstance(item.get("saved"), bool) else False,
            "settings": sanitize(item.get("settings")),
        })
    return slots


def validate_config(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    active = raw.get("active_preset", 1)
    if isinstance(active, bool) or not isinstance(active, int) or not 1 <= active <= PRESET_COUNT:
        active = 1
    return {
        "schema_version": SCHEMA_VERSION,
        "settings": sanitize(raw.get("settings")),
        "active_preset": active,
    }


def validate_user(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    hk = raw.get("hotkeys_enabled", True)
    return {
        "schema_version": SCHEMA_VERSION,
        "hotkeys_enabled": hk if isinstance(hk, bool) else True,
    }


def default_presets() -> dict:
    return {"schema_version": SCHEMA_VERSION, "presets": [default_slot(i + 1) for i in range(PRESET_COUNT)]}


VALIDATORS = {
    "config.json": validate_config,
    "presets.json": lambda raw: {"schema_version": SCHEMA_VERSION, "presets": validate_presets(raw)},
    "user_settings.json": validate_user,
}


def _dump(data) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


# --------------------------------------------------------------------- store
class DataStore:
    """Loads, validates and saves the three local JSON files."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.dir = Path(base_dir) if base_dir else default_data_dir()
        self.backup_dir = self.dir / "backups"
        self.first_run = False
        self.migrated_from_v1 = False
        self.warnings: list[str] = []
        self._backed_up_this_session: set[str] = set()
        self.config = validate_config({})
        self.presets = default_presets()
        self.user = validate_user({})
        self.load()

    # ---- paths / io -------------------------------------------------------
    def path(self, name: str) -> Path:
        return self.dir / name

    def _timestamp(self) -> str:
        t = time.time()
        return time.strftime("%Y%m%d_%H%M%S", time.localtime(t)) + f"_{int((t % 1) * 1000):03d}"

    def _read(self, name: str):
        """Returns (data, state) with state in {"ok", "missing", "corrupt"}."""
        p = self.path(name)
        if not p.exists():
            return None, "missing"
        try:
            return json.loads(p.read_text(encoding="utf-8")), "ok"
        except (OSError, ValueError):
            return None, "corrupt"

    def _backups_of(self, name: str) -> list[Path]:
        stem = Path(name).stem
        if not self.backup_dir.exists():
            return []
        files = [p for p in self.backup_dir.glob(f"{stem}_*.json") if ".corrupt" not in p.name]
        return sorted(files, key=lambda p: p.name, reverse=True)

    def _prune(self, name: str) -> None:
        for old in self._backups_of(name)[BACKUP_KEEP:]:
            try:
                old.unlink()
            except OSError:
                pass

    def make_backup(self, name: str) -> Optional[Path]:
        src = self.path(name)
        if not src.exists():
            return None
        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            dst = self.backup_dir / f"{Path(name).stem}_{self._timestamp()}.json"
            dst.write_bytes(src.read_bytes())
            self._backed_up_this_session.add(name)
            self._prune(name)
            return dst
        except OSError as exc:
            self.warnings.append(f"Backup of {name} failed: {exc}")
            return None

    def _quarantine(self, name: str) -> None:
        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            dst = self.backup_dir / f"{Path(name).stem}.corrupt_{self._timestamp()}.json"
            os.replace(self.path(name), dst)
        except OSError:
            pass

    def _write(self, name: str, data: dict, force_backup: bool = False) -> bool:
        """Atomic write. Returns True if the file was (re)written."""
        text = _dump(data)
        p = self.path(name)
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            if p.exists():
                try:
                    if p.read_text(encoding="utf-8") == text:
                        return False                        # unchanged -> do nothing
                except OSError:
                    pass
                if force_backup or name not in self._backed_up_this_session:
                    self.make_backup(name)
            tmp = p.with_name(p.name + ".tmp")
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, p)
            return True
        except OSError as exc:
            self.warnings.append(f"Could not write {name}: {exc}")
            return False

    # ---- load -------------------------------------------------------------
    def load(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        existing = [n for n in FILES if self.path(n).exists()]
        self.first_run = not existing
        loaded = {}
        for name in FILES:
            data, state = self._read(name)
            if state == "corrupt":
                self._quarantine(name)
                data = self._restore_from_backup(name)
                if data is None:
                    self.warnings.append(f"{name} was unreadable; defaults were created "
                                         f"(the damaged file is kept in backups/)")
                else:
                    self.warnings.append(f"{name} was unreadable; restored from the newest backup")
            loaded[name] = data
        if self.first_run:
            self._migrate_v1(loaded)
        self.config = validate_config(loaded["config.json"])
        self.presets = {"schema_version": SCHEMA_VERSION,
                        "presets": validate_presets(loaded["presets.json"])}
        self.user = validate_user(loaded["user_settings.json"])
        # create missing files / write the validated (repaired) content
        self.save_config()
        self.save_presets()
        self.save_user()

    def _restore_from_backup(self, name: str):
        for b in self._backups_of(name):
            try:
                return json.loads(b.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
        return None

    def _migrate_v1(self, loaded: dict) -> None:
        """Import a V1 config.json (read-only; the V1 file is never modified)."""
        for p in legacy_v1_paths():
            try:
                if not p.exists():
                    continue
                v1 = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(v1, dict) or "settings" not in v1:
                continue
            slots = [default_slot(i + 1) for i in range(PRESET_COUNT)]
            names = []
            v1_presets = v1.get("presets")
            if isinstance(v1_presets, dict):
                names = sorted(v1_presets, key=lambda s: str(s).lower())[:PRESET_COUNT]
                for i, nm in enumerate(names):
                    slots[i] = {"slot": i + 1, "name": clean_name(str(nm), f"Preset {i + 1}"),
                                "saved": True, "settings": sanitize(v1_presets[nm])}
            active = 1
            last = v1.get("last_preset")
            if isinstance(last, str) and last in names:
                active = names.index(last) + 1
            loaded["config.json"] = {"settings": v1.get("settings"), "active_preset": active}
            loaded["presets.json"] = {"presets": slots}
            self.migrated_from_v1 = True
            return

    # ---- save -------------------------------------------------------------
    def save_config(self, force_backup: bool = False) -> bool:
        return self._write("config.json", self.config, force_backup)

    def save_presets(self, force_backup: bool = False) -> bool:
        return self._write("presets.json", self.presets, force_backup)

    def save_user(self, force_backup: bool = False) -> bool:
        return self._write("user_settings.json", self.user, force_backup)

    def save_all(self) -> None:
        self.save_config()
        self.save_presets()
        self.save_user()

    # ---- misc -------------------------------------------------------------
    def log_error(self, text: str) -> None:
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            log = self.dir / "error.log"
            if log.exists() and log.stat().st_size > 200_000:
                log.write_text("", encoding="utf-8")
            with log.open("a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {text}\n")
        except OSError:
            pass
