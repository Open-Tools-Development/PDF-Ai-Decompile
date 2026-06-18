@echo off
REM ====================================================================
REM  PDF Ai Decompile - build a standalone Windows EXE with PyInstaller
REM  Author: Jerry James   License: GPL-3.0   Org: Open-Tools-Development
REM
REM  Folder layout (this script lives in "Scripts"):
REM     <project>\Scripts\            <- all source (app\, backend\, models\,
REM                                     assets\) + this script
REM     <project>\Published_Tool\     <- the finished EXE is placed here
REM     <project>\Doc\                <- architecture / skill documentation
REM     <project>\README.md           <- one level above Scripts
REM
REM  Temporary build folders (build\, *.spec, build_info.py) are created
REM  inside Scripts and can be wiped with clean.bat before commit.
REM ====================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

where py >nul 2>nul
if %ERRORLEVEL%==0 ( set "PY=py -3" ) else ( set "PY=python" )

echo Ensuring PyInstaller and dependencies are installed...
%PY% -m pip install --upgrade pyinstaller >nul 2>nul
%PY% -m pip install -r requirements.txt >nul 2>nul

REM ---- Refresh the icon/splash from source (optional, needs Pillow) ----
%PY% -m assets.make_assets >nul 2>nul

REM ---- Stamp the build date/time into build_info.py ----
echo Stamping build date/time...
%PY% -c "open('build_info.py','w',encoding='utf-8').write('# Auto-generated at build time. Reset by clean.bat.\nBUILD_DATE = \"%date% %time%\"\n')"

if not exist "..\Published_Tool" mkdir "..\Published_Tool"

echo.
echo Building EXE (this can take a couple of minutes)...
echo.

%PY% -m PyInstaller ^
  --noconfirm ^
  --onefile ^
  --windowed ^
  --name "PDFAiDecompile" ^
  --icon "assets\icon.ico" ^
  --splash "assets\splash.png" ^
  --add-data "assets\splash.png;assets" ^
  --add-data "assets\icon.ico;assets" ^
  --add-data "assets\icon_preview.png;assets" ^
  --add-data "LICENSE;." ^
  --collect-all customtkinter ^
  --collect-all pymupdf ^
  --collect-all fitz ^
  --paths "." ^
  --hidden-import app ^
  --hidden-import backend ^
  --distpath "..\Published_Tool" ^
  --workpath "build" ^
  --specpath "." ^
  run_app.py

echo.
if exist "..\Published_Tool\PDFAiDecompile.exe" (
    echo ============================================================
    echo  SUCCESS. Your program is at:
    echo     ..\Published_Tool\PDFAiDecompile.exe
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
