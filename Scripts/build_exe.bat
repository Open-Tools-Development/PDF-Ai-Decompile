@echo off
REM ====================================================================
REM  PDF Image Remover - build a standalone Windows EXE with PyInstaller
REM  Author: Jerry James   License: GPL-3.0
REM
REM  Folder layout (this script lives in "Scripts"):
REM     <project>\Scripts\          <- all source + this script
REM     <project>\Published_Tool\   <- the finished EXE is placed here
REM
REM  The build's temporary folders (build\, *.spec, build_info.py) are
REM  created inside Scripts and can be wiped with clean.bat before commit.
REM ====================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

where py >nul 2>nul
if %ERRORLEVEL%==0 (
    set "PY=py -3"
) else (
    set "PY=python"
)

echo Ensuring PyInstaller and dependencies are installed...
%PY% -m pip install --upgrade pyinstaller >nul 2>nul
%PY% -m pip install -r requirements.txt >nul 2>nul

REM ---- Stamp the build date/time into build_info.py ----
echo Stamping build date/time...
%PY% -c "import datetime,io; open('build_info.py','w',encoding='utf-8').write('# Auto-generated at build time. Reset by clean.bat.\nBUILD_DATE = \"%date% %time%\"\n')"

REM ---- Output EXE goes to ..\Published_Tool ; temp stays in Scripts ----
if not exist "..\Published_Tool" mkdir "..\Published_Tool"

echo.
echo Building EXE (this can take a couple of minutes)...
echo.

%PY% -m PyInstaller ^
  --noconfirm ^
  --onefile ^
  --windowed ^
  --name "PDFImageRemover" ^
  --icon "icon.ico" ^
  --splash "splash.png" ^
  --add-data "splash.png;." ^
  --add-data "icon.ico;." ^
  --add-data "icon_preview.png;." ^
  --add-data "LICENSE;." ^
  --collect-all customtkinter ^
  --collect-all pymupdf ^
  --collect-all fitz ^
  --distpath "..\Published_Tool" ^
  --workpath "build" ^
  --specpath "." ^
  pdf_image_remover.py

echo.
if exist "..\Published_Tool\PDFImageRemover.exe" (
    echo ============================================================
    echo  SUCCESS. Your program is at:
    echo     ..\Published_Tool\PDFImageRemover.exe
    echo ============================================================
    echo  Tip: run clean.bat to delete build temp files before commit.
    echo.
    echo  If Windows Explorer still shows a generic icon for the EXE,
    echo  it is just the Explorer icon cache. The icon is embedded
    echo  correctly - copying the EXE elsewhere or signing out/in
    echo  refreshes it. The icon always shows in the running window.
) else (
    echo Build did not produce an EXE. Scroll up for the PyInstaller error.
)
echo.
pause
endlocal
