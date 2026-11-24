# -*- coding: utf-8 -*-
import json
import os
import tempfile
import unittest
from pathlib import Path

from romanjdm.presets import PresetManager
from romanjdm.storage import DataStore, FILES, validate_config, validate_presets


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name) / "ROMANJDM"
    def tearDown(self):
        self._tmp.cleanup()
    def store(self):
        return DataStore(self.dir)


class FirstRun(Base):
    def test_creates_folder_files_and_four_presets(self):
        s = self.store()
        self.assertTrue(s.first_run)
        for n in FILES:
            self.assertTrue((self.dir / n).exists(), n)
        data = json.loads((self.dir / "presets.json").read_text(encoding="utf-8"))
        self.assertEqual([p["name"] for p in data["presets"]], ["Preset 1", "Preset 2", "Preset 3", "Preset 4"])
        self.assertTrue(all(p["saved"] is False for p in data["presets"]))

    def test_second_start_keeps_everything_and_does_not_rewrite(self):
        s = self.store()
        pm = PresetManager(s)
        pm.save(2, {"x": 5, "y": 33, "duration": 250, "speed": 1.5, "smoothness": 70, "easing": "ease_in"})
        pm.rename(2, "Rifle")
        before = {n: (self.dir / n).read_bytes() for n in FILES}
        mtimes = {n: (self.dir / n).stat().st_mtime_ns for n in FILES}
        s2 = self.store()
        self.assertFalse(s2.first_run)
        self.assertEqual(s2.presets["presets"][1]["name"], "Rifle")
        self.assertEqual(s2.presets["presets"][1]["settings"]["y"], 33)
        self.assertEqual({n: (self.dir / n).read_bytes() for n in FILES}, before)
        self.assertEqual({n: (self.dir / n).stat().st_mtime_ns for n in FILES}, mtimes)


class Persistence(Base):
    def test_values_survive_restart(self):
        s = self.store(); pm = PresetManager(s)
        pm.edit({"x": -7, "y": 41, "duration": 120, "speed": 2.5, "smoothness": 33, "easing": "ease_out"})
        pm.activate(3); pm.edit({"x": 1, "y": 2, "duration": 100, "speed": 1.0, "smoothness": 10, "easing": "linear"})
        pm.flush()
        pm2 = PresetManager(self.store())
        self.assertEqual(pm2.active, 3)
        self.assertEqual(pm2.working["y"], 2)

    def test_update_of_exe_does_not_touch_local_data(self):
        s = self.store(); pm = PresetManager(s); pm.save(1, {"y": 77}); before = (self.dir / "presets.json").read_bytes()
        # a new program version simply starts again on the same folder
        DataStore(self.dir)
        self.assertEqual((self.dir / "presets.json").read_bytes(), before)


class Backups(Base):
    def test_backup_made_before_change_and_pruned(self):
        s = self.store(); pm = PresetManager(s)
        for i in range(15):
            pm.save(1, {"y": i + 1})
        backups = list((self.dir / "backups").glob("presets_*.json"))
        self.assertTrue(1 <= len(backups) <= 10)
        newest = json.loads(sorted(backups)[-1].read_text(encoding="utf-8"))
        self.assertTrue(newest["presets"][0]["saved"])

    def test_reset_keeps_backup_of_old_content(self):
        s = self.store(); pm = PresetManager(s)
        pm.save(4, {"y": 99}); pm.reset(4)
        texts = [p.read_text(encoding="utf-8") for p in (self.dir / "backups").glob("presets_*.json")]
        self.assertTrue(any('"y": 99' in t for t in texts))
        self.assertFalse(pm.slot(4)["saved"])


class Corruption(Base):
    def test_corrupt_presets_restored_from_backup(self):
        s = self.store(); pm = PresetManager(s)
        pm.save(1, {"y": 55}); pm.rename(1, "Keep")
        (self.dir / "presets.json").write_text("{ this is not json", encoding="utf-8")
        s2 = self.store()
        self.assertTrue(any("restored" in w for w in s2.warnings))
        self.assertEqual(len(s2.presets["presets"]), 4)
        self.assertTrue(list((self.dir / "backups").glob("presets.corrupt_*.json")))

    def test_corrupt_config_without_backup_falls_back_to_defaults(self):
        self.store()
        for p in (self.dir / "backups").glob("*") if (self.dir / "backups").exists() else []:
            p.unlink()
        (self.dir / "config.json").write_text("\x00\x01garbage", encoding="utf-8")
        s2 = self.store()
        self.assertEqual(s2.config["settings"]["y"], 20)
        self.assertTrue(s2.warnings)

    def test_validation_clamps_and_repairs(self):
        c = validate_config({"settings": {"x": 99999, "y": "abc", "speed": 99, "easing": "weird"}, "active_preset": 9})
        self.assertEqual(c["settings"]["x"], 2000)
        self.assertEqual(c["settings"]["y"], 20)
        self.assertEqual(c["settings"]["speed"], 5.0)
        self.assertEqual(c["settings"]["easing"], "linear")
        self.assertEqual(c["active_preset"], 1)
        self.assertEqual(len(validate_presets("nonsense")), 4)
        self.assertEqual(len(validate_presets({"presets": [{}] * 10})), 4)


class MigrationV1(Base):
    def test_v1_config_is_imported_and_left_untouched(self):
        v1 = Path(self._tmp.name) / "v1config.json"
        v1.write_text(json.dumps({"version": 1, "settings": {"x": 3, "y": 44, "duration": 200, "smoothness": 60,
                                                              "speed": 1.2, "easing": "ease_in", "repeat": True},
                                  "presets": {"Beta": {"y": 10}, "alpha": {"y": 30}}, "last_preset": "Beta"}),
                      encoding="utf-8")
        import romanjdm.storage as st
        orig = st.legacy_v1_paths
        st.legacy_v1_paths = lambda: [v1]
        try:
            s = self.store()
        finally:
            st.legacy_v1_paths = orig
        self.assertTrue(s.migrated_from_v1)
        self.assertEqual(s.config["settings"]["y"], 44)
        self.assertEqual([p["name"] for p in s.presets["presets"][:2]], ["alpha", "Beta"])
        self.assertEqual(s.config["active_preset"], 2)
        self.assertIn("repeat", v1.read_text(encoding="utf-8"))


class PresetLogic(Base):
    def test_states_modified_reset_and_rename(self):
        pm = PresetManager(self.store())
        self.assertEqual(pm.status(1), "EMPTY")
        pm.save(1, {"y": 12}); self.assertEqual(pm.status(1), "SAVED")
        self.assertFalse(pm.modified)
        pm.edit({"y": 13}); self.assertTrue(pm.modified)
        pm.activate(1); self.assertFalse(pm.modified); self.assertEqual(pm.working["y"], 12)
        self.assertEqual(pm.rename(1, "  A   very   long name that exceeds the limit  "), "A very long name that ex")
        self.assertEqual(pm.rename(1, "   "), "Preset 1")
        pm.activate(2); self.assertEqual(pm.active, 2)
        with self.assertRaises(ValueError):
            pm.activate(5)

    def test_switching_creates_no_threads(self):
        import threading
        pm = PresetManager(self.store()); n = threading.active_count()
        for i in (1, 2, 3, 4, 1, 2):
            pm.activate(i)
        self.assertEqual(threading.active_count(), n)

if __name__ == "__main__":
    unittest.main()
