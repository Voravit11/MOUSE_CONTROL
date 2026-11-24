# -*- coding: utf-8 -*-
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "launcher"))
import launcher as L  # noqa: E402


def release(tag, name=None):
    name = name or f"ROMANJDM_MOUSE_CONTROL_V{tag.lstrip('v')}.exe"
    return {"tag_name": tag, "assets": [
        {"name": "ROMANJDM_MOUSE_CONTROL.exe", "browser_download_url": "https://github.com/a/b/l.exe"},
        {"name": name, "browser_download_url": "https://github.com/a/b/app.exe"},
        {"name": "SHA256SUMS.txt", "browser_download_url": "https://github.com/a/b/s.txt"}]}


def fake_dl(data):
    def dl(url, dest, progress=None):
        Path(dest).write_bytes(data)
    return dl


class Launcher(unittest.TestCase):
    def test_picks_program_not_launcher(self):
        v, name, url, sums = L.pick_assets(release("v2.1.0"))
        self.assertEqual((v, name), ((2, 1, 0), "ROMANJDM_MOUSE_CONTROL_V2.1.0.exe"))

    def test_first_run_downloads_and_verifies(self):
        with tempfile.TemporaryDirectory() as d:
            data = b"program"
            sums = f"{hashlib.sha256(data).hexdigest()}  ROMANJDM_MOUSE_CONTROL_V2.1.0.exe\n"
            exe = L.ensure_latest(Path(d), fetch=lambda: release("v2.1.0"), dl=fake_dl(data),
                                  dl_text=lambda u: sums)
            self.assertEqual(exe.read_bytes(), data)

    def test_bad_hash_is_refused_and_deleted(self):
        with tempfile.TemporaryDirectory() as d:
            sums = f"{'0' * 64}  ROMANJDM_MOUSE_CONTROL_V2.1.0.exe\n"
            with self.assertRaises(L.LaunchError):
                L.ensure_latest(Path(d), fetch=lambda: release("v2.1.0"), dl=fake_dl(b"x"),
                                dl_text=lambda u: sums)
            self.assertEqual(list(Path(d).iterdir()), [])

    def test_offline_uses_cached_copy(self):
        with tempfile.TemporaryDirectory() as d:
            old = Path(d) / "ROMANJDM_MOUSE_CONTROL_V2.0.0.exe"
            old.write_bytes(b"old")

            def offline():
                raise OSError("offline")
            self.assertEqual(L.ensure_latest(Path(d), fetch=offline), old)

    def test_offline_without_cache_is_clean_error(self):
        with tempfile.TemporaryDirectory() as d:
            def offline():
                raise OSError("offline")
            with self.assertRaises(L.LaunchError):
                L.ensure_latest(Path(d), fetch=offline)

    def test_up_to_date_does_not_download(self):
        with tempfile.TemporaryDirectory() as d:
            cur = Path(d) / "ROMANJDM_MOUSE_CONTROL_V2.0.0.exe"
            cur.write_bytes(b"cur")

            def boom(*a, **k):
                raise AssertionError("must not download")
            self.assertEqual(L.ensure_latest(Path(d), fetch=lambda: release("v2.0.0"), dl=boom), cur)

    def test_urls(self):
        self.assertTrue(L.is_allowed_url("https://github.com/a/b"))
        self.assertFalse(L.is_allowed_url("http://github.com/a"))
        self.assertFalse(L.is_allowed_url("https://github.com.evil.com/a"))


if __name__ == "__main__":
    unittest.main()
