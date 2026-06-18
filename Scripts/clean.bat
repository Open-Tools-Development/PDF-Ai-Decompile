@echo off
REM ====================================================================
REM  PDF Ai Decompile - clean build/run artifacts before a git commit
REM  Author: Jerry James   License: GPL-3.0   Org: Open-Tools-Development
REM
REM  Removes the temporary folders/files created while building the EXE
REM  or running the Python scripts. Does NOT touch your source files or
REM  the finished EXE in ..\Published_Tool.
REM ====================================================================
setlocal
cd /d "%~dp0"

echo Cleaning build and cache artifacts in "%cd%" ...

if exist "build"  rmdir /s /q "build"
if exist "dist"   rmdir /s /q "dist"
del /q "*.spec" 2>nul

REM Python bytecode caches (recursively, incl. app\ backend\ models\ assets\)
for /d /r %%d in (__pycache__) do if exist "%%d" rmdir /s /q "%%d"
del /s /q "*.pyc" 2>nul
del /s /q "*.pyo" 2>nul

REM Reset the generated build stamp back to the development placeholder
> build_info.py echo # Auto-generated build information.
>> build_info.py echo # This placeholder is overwritten by build_exe.bat with the real build
>> build_info.py echo # date/time. clean.bat resets it. When running from source it simply reads
>> build_info.py echo # "Development build".
>> build_info.py echo BUILD_DATE = "Development build"

echo.
echo Done. The folder is clean and ready to commit.
echo (Your source files and ..\Published_Tool were left untouched.)
echo.
pause
endlocal
