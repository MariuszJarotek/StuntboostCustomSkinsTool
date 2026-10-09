@echo off
rem Double-click to build "XNB Board Tool.exe" (needs Python 3.9+ from python.org)
cd /d "%~dp0"
where py >nul 2>nul && (py -3 build_exe.py) || (python build_exe.py)
echo.
pause
