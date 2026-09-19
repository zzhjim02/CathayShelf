@echo off
REM Build a release: pack exe, compute SHA256, generate release-note skeleton.
REM Usage: this bat, or: py -3 fab.py --skip-build
setlocal
cd /d "%~dp0"
where py >nul 2>nul && (py -3 "%~dp0fab.py" %* & goto :done)
where python >nul 2>nul && (python "%~dp0fab.py" %* & goto :done)
echo Python not found. Install Python 3.10+ or use the bundled runtime.
pause
:done
endlocal
