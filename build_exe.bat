@echo off
rem Double-click to build XNB Board Tool (needs Python 3.9+ from python.org).
rem Default: folder build zipped for release (fewest antivirus false positives).
rem For a single exe instead, run:  build_exe.bat --onefile
cd /d "%~dp0"
where py >nul 2>nul && (py -3 build_exe.py %*) || (python build_exe.py %*)
echo.
pause
