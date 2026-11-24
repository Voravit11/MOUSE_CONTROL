# -*- coding: utf-8 -*-
"""Four-slot preset logic, independent of Qt so it can be unit tested.

Terms
-----
working   the values currently shown in the GUI / used by the engine
active    the slot (1-4) the working values were last loaded from / saved to
modified  working values differ from the active slot
Slot status shown in the GUI: ACTIVE, SAVED, EMPTY (+ MODIFIED on the active one).
"""
from __future__ import annotations

from typing import Optional

from .settings import PRESET_COUNT, sanitize
from .storage import DataStore, clean_name, default_slot


class PresetManager:
    def __init__(self, store: DataStore):
        self.store = store
        self.working: dict = sanitize(store.config["settings"])
        self.active: int = store.config["active_preset"]

    # ---- read -------------------------------------------------------------
    @property
    def slots(self) -> list[dict]:
        return self.store.presets["presets"]

    def slot(self, n: int) -> dict:
        self._check(n)
        return self.slots[n - 1]

    @property
    def modified(self) -> bool:
        return sanitize(self.working) != self.slot(self.active)["settings"]

    @staticmethod
    def _check(n: int) -> None:
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= PRESET_COUNT:
            raise ValueError(f"preset number must be 1..{PRESET_COUNT}")

    def status(self, n: int) -> str:
        """'EMPTY' or 'SAVED' (activity is separate: see `active`)."""
        return "SAVED" if self.slot(n)["saved"] else "EMPTY"

    # ---- working values -----------------------------------------------------
    def edit(self, settings: dict) -> None:
        """The user changed a value in the GUI."""
        self.working = sanitize(settings)
        self.store.config["settings"] = dict(self.working)
        self.store.config["active_preset"] = self.active

    # ---- slot actions ---------------------------------------------------------
    def activate(self, n: int) -> dict:
        """F1-F4 / Load button: make slot n active and load its values."""
        self._check(n)
        self.active = n
        self.working = dict(self.slot(n)["settings"])
        self.store.config["settings"] = dict(self.working)
        self.store.config["active_preset"] = n
        self.store.save_config()
        return dict(self.working)

    def save(self, n: int, settings: Optional[dict] = None) -> None:
        """Store the working values (or `settings`) in slot n; slot n becomes active."""
        self._check(n)
        s = sanitize(settings if settings is not None else self.working)
        slot = self.slot(n)
        slot["settings"] = s
        slot["saved"] = True
        self.active = n
        self.working = dict(s)
        self.store.config["settings"] = dict(s)
        self.store.config["active_preset"] = n
        self.store.save_presets(force_backup=True)
        self.store.save_config()

    def rename(self, n: int, name: str) -> str:
        self._check(n)
        slot = self.slot(n)
        slot["name"] = clean_name(name, f"Preset {n}")
        self.store.save_presets(force_backup=True)
        return slot["name"]

    def reset(self, n: int) -> None:
        """Back to an empty slot with default values and name."""
        self._check(n)
        self.slots[n - 1] = default_slot(n)
        self.store.save_presets(force_backup=True)
        if n == self.active:
            self.activate(n)

    # ---- persistence ----------------------------------------------------------
    def flush(self) -> None:
        self.store.config["settings"] = dict(self.working)
        self.store.config["active_preset"] = self.active
        self.store.save_config()
        self.store.save_presets()
        self.store.save_user()
