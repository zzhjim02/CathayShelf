@echo off
cd /d "%~dp0"
setlocal
echo === Build CathayShelf.exe  (onefile, windowed, with icon) ===
echo.
py -3 -c "import PyInstaller" >nul 2>nul
if errorlevel 1 (
  echo Installing PyInstaller ...
  py -3 -m pip install pyinstaller
)
py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --name CathayShelf ^
  --icon app.ico --add-data "app.ico;." --add-data "config;config" --collect-all tkinterdnd2 --collect-all opencc --collect-all zhconv --hidden-import chardet --hidden-import zhconv gui.py
if errorlevel 1 goto fail
if not exist "dist\Release" mkdir "dist\Release"
move /y "dist\CathayShelf.exe" "dist\Release\" >nul
echo.
echo [OK] dist\Release\CathayShelf.exe
pause
exit /b 0

:fail
echo.
echo [ERROR] Build failed. See the messages above.
pause
exit /b 1
