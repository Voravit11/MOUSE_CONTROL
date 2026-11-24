# -*- coding: utf-8 -*-
"""PART 13: no Thai (or other non-Arabic) numerals in program text / data."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BAD = re.compile("[\u0e50-\u0e59\u0660-\u0669\u06f0-\u06f9]")


class Numerals(unittest.TestCase):
    def test_source_has_no_non_arabic_digits(self):
        files = list((ROOT / "romanjdm").glob("*.py")) + [ROOT / "main.py"]
        for f in files:
            self.assertIsNone(BAD.search(f.read_text(encoding="utf-8")), f.name)

    def test_formatting_produces_ascii_digits(self):
        from romanjdm.settings import sanitize, effective_duration_ms
        s = sanitize({"x": 10, "y": 25, "speed": 2.5})
        text = f"X: {s['x']} Y: {s['y']} Speed: {s['speed']:.1f} {effective_duration_ms(100, 1):.0f}"
        self.assertIsNone(BAD.search(text))
        self.assertTrue(text.isascii())

    def test_json_files_have_ascii_digits(self):
        import tempfile
        from romanjdm.storage import DataStore
        with tempfile.TemporaryDirectory() as d:
            DataStore(Path(d) / "x")
            for f in (Path(d) / "x").glob("*.json"):
                self.assertIsNone(BAD.search(f.read_text(encoding="utf-8")))

if __name__ == "__main__":
    unittest.main()
