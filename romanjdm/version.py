# -*- coding: utf-8 -*-
"""Single source of truth for version / release metadata."""

APP_NAME = "ROMANJDM MOUSE CONTROL"
APP_VERSION = "2.0.0"
EXE_NAME = f"ROMANJDM_MOUSE_CONTROL_V{APP_VERSION}.exe"

# GitHub release metadata. Set GITHUB_OWNER to the GitHub account that owns the
# repository before building if you want the optional "Check for updates"
# button to work. While it still holds the placeholder the button just
# explains that updates are not configured.
GITHUB_OWNER = "YOUR_GITHUB_USERNAME"
GITHUB_REPO = "ROMANJDM-MOUSE-CONTROL"


def updates_configured() -> bool:
    return bool(GITHUB_OWNER) and GITHUB_OWNER != "YOUR_GITHUB_USERNAME"
