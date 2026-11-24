# -*- coding: utf-8 -*-
"""ROMANJDM MOUSE CONTROL - launcher.

This is the ONLY file a user needs. Double-click it and it:
  1. asks GitHub Releases for the latest published version,
  2. downloads the real program (once, or when a newer version exists),
  3. checks its SHA-256 against the release's SHA256SUMS.txt,
  4. starts it.

If there is no internet it simply starts the copy it downloaded last time.
Only the standard library is used, so this EXE stays small.
Downloaded programs live in  %LOCALAPPDATA%\\ROMANJDM\\app\\  (user data is never touched).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

try:                                    # filled in by the GitHub Actions build (owner/repo)
    from launcher_config import GITHUB_REPOSITORY          # type: ignore
except Exception:                       # running from source / not configured
    GITHUB_REPOSITORY = "YOUR_GITHUB_USERNAME/ROMANJDM-MOUSE-CONTROL"

TITLE = "ROMANJDM MOUSE CONTROL"
ALLOWED_HOSTS = ("api.github.com", "github.com", "objects.githubusercontent.com",
                 "release-assets.githubusercontent.com")
APP_EXE_RE = re.compile(r"^ROMANJDM_MOUSE_CONTROL_V\d+(\.\d+){0,3}\.exe$", re.IGNORECASE)
MAX_BYTES = 300 * 1024 * 1024
API_TIMEOUT = 8


class LaunchError(Exception):
    pass


# ---------------------------------------------------------------- helpers (testable, no GUI)
def app_dir() -> Path:
    base = os.environ.get("ROMANJDM_LAUNCHER_DIR")
    if base:
        return Path(base)
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "ROMANJDM" / "app"


def is_allowed_url(url: str) -> bool:
    try:
        u = urlparse(url)
    except ValueError:
        return False
    return u.scheme == "https" and (u.hostname or "").lower() in ALLOWED_HOSTS


def parse_version(text: str) -> tuple:
    m = re.match(r"^\s*[vV]?(\d+(?:\.\d+){0,3})", str(text))
    if not m:
        raise ValueError(f"not a version: {text!r}")
    parts = tuple(int(p) for p in m.group(1).split("."))
    return parts + (0,) * (3 - len(parts))


def parse_sha256sums(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        m = re.match(r"^\s*([0-9a-fA-F]{64})\s+\*?(.+?)\s*$", line)
        if m:
            out[m.group(2)] = m.group(1).lower()
    return out


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def pick_assets(release: dict) -> tuple:
    """-> (version_tuple, exe_name, exe_url, sums_url). Ignores the launcher's own asset."""
    exe = sums = None
    for a in release.get("assets") or []:
        name, url = str(a.get("name", "")), str(a.get("browser_download_url", ""))
        if APP_EXE_RE.match(name) and exe is None:
            exe = (name, url)
        elif name.upper() == "SHA256SUMS.TXT":
            sums = url
    if not exe or not sums:
        raise LaunchError("The latest release has no program file or no SHA256SUMS.txt")
    return parse_version(release.get("tag_name", "")), exe[0], exe[1], sums


def cached_apps(folder: Path) -> list:
    """Downloaded program files, newest version first."""
    found = []
    if folder.is_dir():
        for p in folder.iterdir():
            if p.is_file() and APP_EXE_RE.match(p.name):
                try:
                    found.append((parse_version(p.name.split("_V", 1)[1][:-4]), p))
                except ValueError:
                    pass
    return [p for _, p in sorted(found, key=lambda t: t[0], reverse=True)]


def _open(url: str, timeout: int):
    if not is_allowed_url(url):
        raise LaunchError("Blocked URL (not an https GitHub address)")
    req = urllib.request.Request(url, headers={"User-Agent": "ROMANJDM-Launcher",
                                               "Accept": "application/vnd.github+json, */*"})
    resp = urllib.request.urlopen(req, timeout=timeout)          # noqa: S310 (checked above)
    if not is_allowed_url(resp.geturl()):
        resp.close()
        raise LaunchError("Blocked redirect target")
    return resp


def fetch_latest(repo: str = GITHUB_REPOSITORY) -> dict:
    with _open(f"https://api.github.com/repos/{repo}/releases/latest", API_TIMEOUT) as r:
        return json.loads(r.read(2_000_000).decode("utf-8"))


def download(url: str, dest: Path, progress=None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    try:
        with _open(url, 30) as resp, open(tmp, "wb") as f:
            total = int(resp.headers.get("Content-Length") or 0)
            if total > MAX_BYTES:
                raise LaunchError("File is unexpectedly large")
            done = 0
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                done += len(chunk)
                if done > MAX_BYTES:
                    raise LaunchError("File is unexpectedly large")
                f.write(chunk)
                if progress:
                    progress(done, total)
        tmp.replace(dest)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def download_text(url: str) -> str:
    with _open(url, 30) as r:
        return r.read(1_000_000).decode("utf-8", errors="replace")


def ensure_latest(folder: Path, progress=None, status=None, fetch=fetch_latest,
                  dl=download, dl_text=download_text) -> Path:
    """Return the program file to run (downloading/updating it if needed)."""
    local = cached_apps(folder)
    try:
        version, name, exe_url, sums_url = pick_assets(fetch())
    except Exception as exc:
        if local:
            return local[0]                        # offline / GitHub unreachable: use last copy
        raise LaunchError(f"Could not reach GitHub and no program is downloaded yet.\n\n{exc}") from exc

    target = folder / name
    if target.exists() and target in local[:1]:
        return target                              # already the newest we know of
    if local and parse_version(local[0].name.split("_V", 1)[1][:-4]) >= version:
        return local[0]

    if status:
        status(f"Downloading {name} ...")
    dl(exe_url, target, progress)
    try:
        expected = parse_sha256sums(dl_text(sums_url)).get(name)
        if not expected or sha256_file(target) != expected:
            raise LaunchError("SHA-256 check failed - the downloaded file is not the published one.")
    except Exception as exc:
        target.unlink(missing_ok=True)
        if local:
            return local[0]
        raise LaunchError(str(exc)) from exc

    for old in local:                              # keep only the newest + previous (rollback)
        if old != target and old not in local[:1]:
            old.unlink(missing_ok=True)
    return target


# ---------------------------------------------------------------- GUI glue
def _message(text: str, error: bool = False) -> None:
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, TITLE, 0x10 if error else 0x40)
    except Exception:
        print(text, file=sys.stderr)


class _Progress:
    """Small progress window (tkinter). Silently does nothing if tkinter is unavailable."""

    def __init__(self):
        self.root = None
        try:
            import tkinter as tk
            from tkinter import ttk
            self.root = tk.Tk()
            self.root.title(TITLE)
            self.root.resizable(False, False)
            self.root.attributes("-topmost", True)
            self.label = tk.Label(self.root, text="Starting ...", padx=24, pady=12)
            self.label.pack()
            self.bar = ttk.Progressbar(self.root, length=320, mode="indeterminate")
            self.bar.pack(padx=24, pady=(0, 18))
            self.bar.start(12)
            self.root.update()
        except Exception:
            self.root = None

    def status(self, text):
        if self.root:
            self.label.config(text=text)
            self.root.update()

    def progress(self, done, total):
        if self.root and total:
            self.bar.stop()
            self.bar.config(mode="determinate", maximum=total, value=done)
            self.label.config(text=f"Downloading ... {done * 100 // total}%")
            self.root.update()

    def close(self):
        if self.root:
            try:
                self.root.destroy()
            except Exception:
                pass


def main() -> int:
    if GITHUB_REPOSITORY.startswith("YOUR_GITHUB_USERNAME"):
        _message("This launcher is not configured with a GitHub repository.\n"
                 "Download it from the project's GitHub Releases page.", error=True)
        return 1
    ui = _Progress()
    try:
        exe = ensure_latest(app_dir(), ui.progress, ui.status)
    except Exception as exc:
        ui.close()
        _message(str(exc), error=True)
        return 1
    ui.close()
    flags = 0x00000008 | 0x00000200 if sys.platform == "win32" else 0   # DETACHED | NEW_GROUP
    subprocess.Popen([str(exe)], cwd=str(exe.parent), creationflags=flags, close_fds=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
