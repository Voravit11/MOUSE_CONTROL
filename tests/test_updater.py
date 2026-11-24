# -*- coding: utf-8 -*-
import hashlib
import tempfile
import unittest
from pathlib import Path

from romanjdm import updater
from romanjdm.updater import UpdateError


class Versions(unittest.TestCase):
    def test_compare(self):
        self.assertTrue(updater.is_newer("v2.0.1", "2.0.0"))
        self.assertTrue(updater.is_newer("2.1", "2.0.9"))
        self.assertFalse(updater.is_newer("2.0.0", "2.0.0"))
        self.assertFalse(updater.is_newer("1.9.9", "2.0.0"))
        with self.assertRaises(ValueError):
            updater.parse_version("latest")


class Checksums(unittest.TestCase):
    def test_parse_and_verify(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "ROMANJDM_MOUSE_CONTROL_V2.1.0.exe"
            f.write_bytes(b"binary-data")
            h = hashlib.sha256(b"binary-data").hexdigest()
            sums = f"{h}  {f.name}\n{'0' * 64} *other.exe\n"
            self.assertEqual(updater.parse_sha256sums(sums)[f.name], h)
            updater.verify_sha256(f, sums, f.name)
            f.write_bytes(b"tampered")
            with self.assertRaises(UpdateError):
                updater.verify_sha256(f, sums, f.name)
            with self.assertRaises(UpdateError):
                updater.verify_sha256(f, sums, "missing.exe")


class Urls(unittest.TestCase):
    def test_only_https_github(self):
        self.assertTrue(updater.is_allowed_url("https://github.com/a/b/releases/download/v1/x.exe"))
        self.assertTrue(updater.is_allowed_url("https://objects.githubusercontent.com/x"))
        self.assertFalse(updater.is_allowed_url("http://github.com/x"))
        self.assertFalse(updater.is_allowed_url("https://evil.example.com/x.exe"))
        self.assertFalse(updater.is_allowed_url("https://github.com.evil.com/x"))
        self.assertFalse(updater.is_allowed_url("file:///C:/x.exe"))

    def test_release_json(self):
        rel = updater.parse_release_json({
            "tag_name": "v2.1.0", "body": "notes", "html_url": "https://github.com/a/b/releases/tag/v2.1.0",
            "assets": [{"name": "ROMANJDM_MOUSE_CONTROL.exe", "browser_download_url": "https://github.com/a/b/launcher.exe"},
                       {"name": "ROMANJDM_MOUSE_CONTROL_V2.1.0.exe", "browser_download_url": "https://github.com/a/b/x.exe"},
                       {"name": "SHA256SUMS.txt", "browser_download_url": "https://github.com/a/b/s.txt"}]})
        self.assertEqual(rel.version, "2.1.0")
        self.assertEqual(rel.exe_name, "ROMANJDM_MOUSE_CONTROL_V2.1.0.exe")
        with self.assertRaises(UpdateError):
            updater.parse_release_json({"tag_name": "v2.1.0", "assets": []})

    def test_signature_policy(self):
        self.assertTrue(updater.signature_allows_install("Valid"))
        self.assertTrue(updater.signature_allows_install("NotSigned"))
        self.assertFalse(updater.signature_allows_install("HashMismatch"))
        self.assertFalse(updater.signature_allows_install("NotTrusted"))

    def test_no_internet_is_a_clean_error(self):
        orig = updater._open
        updater._open = lambda *a, **k: (_ for _ in ()).throw(OSError("offline"))
        try:
            with self.assertRaises(UpdateError):
                updater.fetch_latest_release("o", "r")
        finally:
            updater._open = orig

if __name__ == "__main__":
    unittest.main()
