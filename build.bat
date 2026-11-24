@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo ============================================================
echo  ROMANJDM MOUSE CONTROL : build
echo ============================================================

rem ---- find Python 3.13 (falls back to "python") ----
set "PY=py -3.13"
%PY% --version >nul 2>nul
if errorlevel 1 (
    echo Python 3.13 launcher not found, falling back to "python"
    set "PY=python"
)
%PY% --version || goto :fail

rem ---- version from the single source of truth ----
for /f %%v in ('%PY% -c "from romanjdm.version import APP_VERSION; print(APP_VERSION)"') do set "VERSION=%%v"
if "%VERSION%"=="" goto :fail
set "EXE=ROMANJDM_MOUSE_CONTROL_V%VERSION%.exe"
echo Building version %VERSION%  ->  %EXE%

rem ---- virtual environment + dependencies ----
if not exist .venv (
    %PY% -m venv .venv || goto :fail
)
call .venv\Scripts\activate.bat || goto :fail
python -m pip install --upgrade pip || goto :fail
pip install -r requirements.txt || goto :fail

rem ---- unit tests (no real mouse is touched) ----
echo.
echo [1/4] Running unit tests ...
python -m unittest discover -s tests -t . || goto :fail

rem ---- PyInstaller: ONE standalone windowed EXE ----
echo.
echo [2/4] Building EXE ...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
pyinstaller --noconfirm --clean --onefile --windowed --name ROMANJDM_MOUSE_CONTROL_V%VERSION% --exclude-module tkinter main.py || goto :fail
if not exist "dist\%EXE%" goto :fail

rem ---- release folder: only the files that go to GitHub Releases ----
if exist release rmdir /s /q release
mkdir release
copy /Y "dist\%EXE%" "release\%EXE%" >nul || goto :fail

rem ---- self test of the real EXE (headless, fake mouse, temp data folder) ----
echo.
echo [3/4] Self test of the built EXE ...
set "ST=%TEMP%\romanjdm_selftest.json"
if exist "%ST%" del "%ST%"
start /wait "" "release\%EXE%" --selftest --selftest-out "%ST%"
if errorlevel 1 (
    echo SELF TEST FAILED
    if exist "%ST%" type "%ST%"
    goto :fail
)
echo Self test OK
type "%ST%"

rem ---- SHA-256 checksum file ----
echo.
echo [4/4] Writing SHA256SUMS.txt ...
powershell -NoProfile -Command "Get-FileHash -Algorithm SHA256 -LiteralPath 'release\%EXE%' | ForEach-Object { $_.Hash.ToLower() + '  ' + (Split-Path $_.Path -Leaf) } | Set-Content -Encoding ascii 'release\SHA256SUMS.txt'" || goto :fail
type release\SHA256SUMS.txt

echo.
echo BUILD OK
echo Upload these files to GitHub Releases:
echo     %CD%\release\%EXE%
echo     %CD%\release\SHA256SUMS.txt
echo Then test the EXE by hand (see README_TH.md, chapter 9, step 9).
pause
exit /b 0

:fail
echo.
echo BUILD FAILED  (read the messages above)
pause
exit /b 1
