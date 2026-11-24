# ROMANJDM MOUSE CONTROL V2.0.0

Windows 10/11 desktop tool. **Hold Left + Right mouse buttons together** and the program moves the mouse
continuously (relative movement). **Release either button and it stops immediately.**

Thai user guide: [README_TH.md](README_TH.md) (also as PDF: `คู่มือการใช้งาน_ROMANJDM_V2.0.0.pdf`).

## For users (one file, nothing else)
Download **`ROMANJDM_MOUSE_CONTROL.exe`** (the small launcher) from the GitHub **Releases** page and double-click it.
It fetches the real program from GitHub by itself (first run only, verified with SHA-256), starts it, and
re-checks for newer versions on every start. No Python, no folders, no setup. Offline? It starts the copy it
downloaded last time. Permanent link:
`[https://github.com/<owner>/<repo>/releases/latest/download/ROMANJDM_MOUSE_CONTROL.exe](https://github.com/Voravit11/MOUSE_CONTROL.git)`

Downloaded programs are kept in `%LOCALAPPDATA%\ROMANJDM\app\`; your settings stay in `%LOCALAPPDATA%\ROMANJDM\`.

## What changed from V1.0.0
| V1.0.0 | V2.0.0 |
|---|---|
| One finite motion per press (`_latched` + `_motion()`), "Repeat" restarted it and reset progress | Single worker thread, delta-time integration (`time.perf_counter()`), no reset, no seams while the buttons stay down |
| Easing applied to every cycle | Easing shapes only the start-up ramp; steady rate afterwards |
| `config.json` next to the EXE | `%LOCALAPPDATA%\ROMANJDM\` (config.json, presets.json, user_settings.json, backups\) |
| Named presets in a combo box | 4 slots on F1-F4 (Save / Load / Edit Name / Reset) |
| F8 start/stop, F9 emergency | kept; F1-F4 added; modifier-key guard; hotkeys can be switched off (F9 never) |
| - | Optional, user-confirmed update check (SHA-256 + Authenticode check) |

V1 settings/presets are imported on first start (the V1 file is never modified).

## Movement model
`rate = distance * Speed / (Duration / 1000)` in mouse units per second. Each tick:
`acc += rate * envelope * dt`; the whole-pixel part is sent through `SendInput` (relative move), the fraction stays
in the accumulator. Smoothness 1..100 sets the tick interval 8 ms .. 1 ms. Easing = start-up envelope over
`Duration / Speed` seconds, then 1.0.

Safety design: only `MOUSEEVENTF_MOVE` is injected, mouse buttons are never pressed or released, state is polled
(`GetAsyncKeyState`, no hooks), no anti-cheat / security bypass. Check the rules of the game/software you use it with.

## Project layout
```
main.py                 entry point (PyInstaller entry)
launcher/launcher.py     the one-file launcher (stdlib only)
.github/workflows/      automatic build + release
romanjdm/
  version.py            version, GitHub owner/repo
  settings.py           defaults, limits, validation, movement math (no Windows/Qt)
  winapi.py             ctypes SendInput / GetAsyncKeyState / mutex
  hotkeys.py            polled global hotkeys with collision guards
  engine.py             continuous movement engine (one thread)
  storage.py            local JSON storage, backups, recovery, V1 migration
  presets.py            4-slot preset logic (no Qt)
  updater.py            optional update check/download/verify
  gui.py                PySide6 GUI
  app.py                start-up, --selftest
  testing.py            fake backend (tests, selftest)
tests/                  unittest suite (python -m unittest discover -s tests -t .)
tools/check_names.py    tiny static check
build.bat               tests -> PyInstaller -> EXE self-test -> SHA256SUMS
```

## Build (developer, Windows 10/11, Python 3.13)
```
build.bat
```
Output in `release\`: `ROMANJDM_MOUSE_CONTROL_V2.0.0.exe` and `SHA256SUMS.txt`
(PyInstaller `--onefile --windowed`). Run from source: `pip install -r requirements.txt` then `python main.py`.

## Release instructions (automatic)
1. Create a GitHub repository and upload this whole folder (see "Upload" below). `.gitignore` keeps binaries and user data out.
2. The workflow `.github/workflows/release.yml` runs on every push to `main`: if the `APP_VERSION` in
   `romanjdm/version.py` has no release yet, GitHub tests, builds the program + launcher, writes `SHA256SUMS.txt`
   and publishes release `v<APP_VERSION>`. The repository owner/name are injected automatically.
3. New version = change `APP_VERSION`, push. Users get it the next time they open the launcher.

Manual build is still possible with `build.bat` (developer only).

## Local data (never uploaded)
`%LOCALAPPDATA%\ROMANJDM\` - `config.json`, `presets.json`, `user_settings.json`, `backups\`, `error.log`.
There is no cloud sync and nothing is sent to GitHub. Updating the EXE never touches this folder.
