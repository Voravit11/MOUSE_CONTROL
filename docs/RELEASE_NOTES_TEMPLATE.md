## ROMANJDM MOUSE CONTROL V2.0.0

Download **only** `ROMANJDM_MOUSE_CONTROL_V2.0.0.exe` and double-click it. No Python or other software is needed.
`SHA256SUMS.txt` is optional: use it to check that the download is intact.

### What's new
- Continuous movement engine: hold Left + Right mouse and it keeps moving with no pauses or restarts; release either button and it stops.
- 4 presets on F1-F4 (Save / Load / Edit Name / Reset).
- All your data stays on your PC in `%LOCALAPPDATA%\ROMANJDM`; updating never touches it.
- Optional "Check for Updates" button (only runs when you click it; verifies SHA-256).
- Settings and presets from V1 are imported automatically on first start (the old file is not changed).

### Verify the download
PowerShell:  `Get-FileHash .\ROMANJDM_MOUSE_CONTROL_V2.0.0.exe -Algorithm SHA256`
The value must equal the line in `SHA256SUMS.txt`.

Note: the EXE is not code-signed unless stated here, so Windows SmartScreen may show a warning. Use it only if the SHA-256 matches.
