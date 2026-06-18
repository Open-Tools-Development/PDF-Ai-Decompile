@echo off
REM ====================================================================
REM  PDF Ai Decompile - install Python dependencies (run once)
REM  Author: Jerry James   License: GPL-3.0
REM  Org: Open-Tools-Development
REM ====================================================================
setlocal
echo Installing Python dependencies for PDF Ai Decompile...
echo.
where py >nul 2>nul
if %ERRORLEVEL%==0 ( set "PY=py -3" ) else ( set "PY=python" )

%PY% -m pip install --upgrade pip
%PY% -m pip install -r requirements.txt

echo.
if %ERRORLEVEL%==0 (
    echo Done. You can now run the tool with run.bat
) else (
    echo Something went wrong. Make sure Python 3.8+ is installed and on PATH.
)
echo.
pause
endlocal
