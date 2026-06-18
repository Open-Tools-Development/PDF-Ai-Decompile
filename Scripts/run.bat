@echo off
REM ====================================================================
REM  PDF Ai Decompile - run from source (Python)
REM ====================================================================
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %ERRORLEVEL%==0 ( set "PY=py -3" ) else ( set "PY=python" )
%PY% run_app.py
if %ERRORLEVEL% neq 0 (
    echo.
    echo The program exited with an error. If dependencies are missing,
    echo run install_dependencies.bat first.
    pause
)
endlocal
