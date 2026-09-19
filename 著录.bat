@echo off
cd /d "%~dp0"
setlocal
set "PYEXE="
set "SELFEXE="

rem [1] prefer the bundled portable runtime (no install, no dependencies)
if not defined PYEXE (
  if exist "%~dp0runtime\python.exe" (
    "%~dp0runtime\python.exe" -c "import tkinter, fitz" >nul 2>nul
    if not errorlevel 1 (
      set PYEXE="%~dp0runtime\pythonw.exe"
      set SELFEXE="%~dp0runtime\python.exe"
    )
  )
)

rem [2] system Python 3
if not defined PYEXE (
  py -3 -c "import tkinter, fitz" >nul 2>nul
  if not errorlevel 1 (
    set PYEXE=py -3
    set SELFEXE=py -3
  )
)

if not defined PYEXE (
  python -c "import tkinter, fitz" >nul 2>nul
  if not errorlevel 1 (
    set PYEXE=python
    set SELFEXE=python
  )
)

rem [3] common install locations
if not defined PYEXE (
  for %%P in (
    "%ProgramFiles%\Python310\python.exe"
    "%ProgramFiles%\Python311\python.exe"
    "%ProgramFiles%\Python312\python.exe"
    "%ProgramFiles%\Python313\python.exe"
    "%ProgramFiles%\Python314\python.exe"
    "%LocalAppData%\Programs\Python\Python311\python.exe"
    "%LocalAppData%\Programs\Python\Python312\python.exe"
    "%LocalAppData%\Programs\Python\Python313\python.exe"
    "%LocalAppData%\Python\pythoncore-3.14-64\python.exe"
  ) do (
    if not defined PYEXE (
      if exist %%P (
        %%P -c "import tkinter, fitz" >nul 2>nul
        if not errorlevel 1 (
          set PYEXE=%%P
          set SELFEXE=%%P
        )
      )
    )
  )
)

if not defined PYEXE goto nopy
if /i "%~1"=="--selftest" (
  echo PYEXE=%PYEXE%
  %SELFEXE% "%~dp0gui.py" --selftest
  exit /b 0
)
%PYEXE% "%~dp0gui.py" %*
if errorlevel 1 pause
exit /b 0

:nopy
echo.
echo [ERROR] No usable Python 3 with tkinter + PyMuPDF(fitz) found,
echo         and the bundled runtime folder "runtime" is missing.
echo.
echo Options:
echo   1) Use the standalone EXE in dist\Release\ (no Python needed), or
echo   2) Install Python 3 from python.org, then run:
echo          py -3 -m pip install pymupdf
echo.
pause
exit /b 1
