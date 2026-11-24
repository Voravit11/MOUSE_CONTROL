# -*- coding: utf-8 -*-
"""Optional update helper. Nothing here runs unless the user clicks
"Check for updates" and then confirms the download.

Safety rules
------------
* Only a built EXE from GitHub Releases is downloaded - never Python source.
* The EXE must match its SHA-256 in the release's SHA256SUMS.txt, otherwise it
  is deleted and the update is refused.
* If the EXE carries a Windows (Authenticode) signature it must be "Valid";
  an unsigned EXE is reported as such and the user decides. A signature that is
  present but invalid is always refused.
* The running EXE is NOT overwritten: the new EXE is saved beside it under its
  own versioned name, so the old version stays as the backup/rollback.
* %LOCALAPPDATA%\\ROMANJDM (presets, config) is never touched.
* Only https URLs on GitHub hosts are accepted.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

from .version import APP_VERSION, GITHUB_OWNER, GITHUB_REPO

ALLOWED_HOSTS = (
    "api.github.com", "github.com", "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
)
TIMEOUT_S = 10
MAX_EXE_BYTES = 300 * 1024 * 1024


class UpdateError(Exception):
    pass


@dataclass
class ReleaseInfo:
    tag: str
    version: str
    notes: str
    page_url: str
    exe_name: str
    exe_url: str
    sums_url: str


def parse_version(text: str) -> tuple[int, ...]:
    m = re.match(r"^\s*[vV]?(\d+(?:\.\d+){0,3})", str(text))
    if not m:
        raise ValueError(f"not a version: {text!r}")
    parts = tuple(int(p) for p in m.group(1).split("."))
    return parts + (0,) * (3 - len(parts)) if len(parts) < 3 else parts


def is_newer(remote: str, local: str = APP_VERSION) -> bool:
    return parse_version(remote) > parse_version(local)


def is_allowed_url(url: str) -> bool:
    try:
        u = urlparse(url)
    except ValueError:
        return False
    return u.scheme == "https" and (u.hostname or "").lower() in ALLOWED_HOSTS


def _open(url: str, timeout: int = TIMEOUT_S):
    if not is_allowed_url(url):
        raise UpdateError("Blocked URL (not an https GitHub address)")
    req = urllib.request.Request(url, headers={"User-Agent": f"ROMANJDM-MOUSE-CONTROL/{APP_VERSION}",
                                               "Accept": "application/vnd.github+json, */*"})
    resp = urllib.request.urlopen(req, timeout=timeout)       # noqa: S310 (checked above)
    if not is_allowed_url(resp.geturl()):
        resp.close()
        raise UpdateError("Blocked redirect target")
    return resp


def parse_release_json(data: dict) -> ReleaseInfo:
    tag = str(data.get("tag_name", ""))
    version = ".".join(str(p) for p in parse_version(tag))
    exe = sums = None
    for a in data.get("assets", []) or []:
        name, url = str(a.get("name", "")), str(a.get("browser_download_url", ""))
        if re.match(r"^ROMANJDM_MOUSE_CONTROL_V\d", name, re.I) and name.lower().endswith(".exe") and exe is None:
            exe = (name, url)
        elif name.upper() == "SHA256SUMS.TXT":
            sums = (name, url)
    if not exe or not sums:
        raise UpdateError("The latest release has no EXE or no SHA256SUMS.txt")
    return ReleaseInfo(tag, version, str(data.get("body") or ""), str(data.get("html_url") or ""),
                       exe[0], exe[1], sums[1])


def fetch_latest_release(owner: str = GITHUB_OWNER, repo: str = GITHUB_REPO) -> ReleaseInfo:
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    try:
        with _open(url) as resp:
            data = json.loads(resp.read(2_000_000).decode("utf-8"))
    except UpdateError:
        raise
    except Exception as exc:                  # no internet, rate limit, bad JSON ...
        raise UpdateError(f"Could not reach GitHub: {exc}") from exc
    return parse_release_json(data)


def parse_sha256sums(text: str) -> dict[str, str]:
    """Parse `<hash>  <file>` lines (also `<hash> *<file>`)."""
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


def verify_sha256(path: Path, sums_text: str, exe_name: str) -> None:
    expected = parse_sha256sums(sums_text).get(exe_name)
    if not expected:
        raise UpdateError(f"{exe_name} is not listed in SHA256SUMS.txt")
    actual = sha256_file(path)
    if actual != expected:
        raise UpdateError("SHA-256 mismatch - the downloaded file is not the published one")


def download_text(url: str) -> str:
    with _open(url) as resp:
        return resp.read(1_000_000).decode("utf-8", errors="replace")


def download_file(url: str, dest: Path, progress: Optional[Callable[[int, int], None]] = None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    try:
        with _open(url, timeout=30) as resp, open(tmp, "wb") as f:
            total = int(resp.headers.get("Content-Length") or 0)
            if total > MAX_EXE_BYTES:
                raise UpdateError("File is unexpectedly large")
            done = 0
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                done += len(chunk)
                if done > MAX_EXE_BYTES:
                    raise UpdateError("File is unexpectedly large")
                f.write(chunk)
                if progress:
                    progress(done, total)
        tmp.replace(dest)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def authenticode_status(path: Path) -> str:
    """'Valid', 'NotSigned', another Windows status string, or 'Unknown'."""
    if sys.platform != "win32":
        return "Unknown"
    try:
        cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
               "(Get-AuthenticodeSignature -LiteralPath $args[0]).Status", str(path)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30,
                           creationflags=0x08000000)       # CREATE_NO_WINDOW
        return (r.stdout or "").strip() or "Unknown"
    except Exception:
        return "Unknown"


def signature_allows_install(status: str) -> bool:
    """Valid or NotSigned/Unknown may continue (the user is told); anything else is refused."""
    return status in ("Valid", "NotSigned", "Unknown")


def target_folder() -> Path:
    """Beside the running EXE if writable, otherwise the user's Downloads folder."""
    if getattr(sys, "frozen", False):
        d = Path(sys.executable).resolve().parent
        try:
            probe = d / ".romanjdm_write_test"
            probe.write_text("x")
            probe.unlink()
            return d
        except OSError:
            pass
    return Path.home() / "Downloads"
