@echo off
REM PhotoScribe - Install & Launch Script for Windows
REM Requires Python 3.10-3.13 installed and in PATH

echo.
echo  PhotoScribe
echo  AI-powered photo metadata generator
echo.

REM Check for compatible Python (try versioned first, then generic)
set PYTHON=
set PY_VER=

REM Try specific versions (newest first)
for %%V in (3.13 3.12 3.11 3.10) do (
    where python%%V >nul 2>&1
    if not errorlevel 1 (
        set PYTHON=python%%V
        set PY_VER=%%V
        goto :found_python
    )
)

REM Try py launcher (Windows Python Launcher)
where py >nul 2>&1
if not errorlevel 1 (
    for %%V in (-3.13 -3.12 -3.11 -3.10) do (
        py %%V --version >nul 2>&1
        if not errorlevel 1 (
            set PYTHON=py %%V
            set PY_VER=%%V
            goto :found_python
        )
    )
)

REM Try generic python3 / python
where python3 >nul 2>&1
if not errorlevel 1 (
    for /f "tokens=2 delims= " %%A in ('python3 --version 2^>^&1') do set PY_VER=%%A
    set PYTHON=python3
    goto :check_version
)

where python >nul 2>&1
if not errorlevel 1 (
    for /f "tokens=2 delims= " %%A in ('python --version 2^>^&1') do set PY_VER=%%A
    set PYTHON=python
    goto :check_version
)

echo  [ERROR] Python not found.
echo  Download Python 3.13 from: https://www.python.org/downloads/
echo  IMPORTANT: Check "Add Python to PATH" during installation.
pause
exit /b 1

:check_version
REM Basic check - extract major.minor
for /f "tokens=1,2 delims=." %%A in ("%PY_VER%") do (
    set PY_MAJOR=%%A
    set PY_MINOR=%%B
)
if "%PY_MAJOR%" NEQ "3" (
    echo  [ERROR] Python 3 required, found Python %PY_VER%
    pause
    exit /b 1
)
if %PY_MINOR% LSS 10 (
    echo  [ERROR] Python %PY_VER% too old. Need 3.10-3.13.
    echo  Download from: https://www.python.org/downloads/
    pause
    exit /b 1
)
if %PY_MINOR% GTR 13 (
    echo  [ERROR] Python %PY_VER% too new. PySide6 and rawpy require 3.10-3.13.
    echo  Download Python 3.13 from: https://www.python.org/downloads/release/python-3130/
    pause
    exit /b 1
)

:found_python
echo  [OK] Python %PY_VER% found

REM Check Ollama
ollama --version >nul 2>&1
if errorlevel 1 (
    echo  [WARNING] Ollama not installed.
    echo.
    echo  PhotoScribe needs Ollama to run AI models locally.
    echo  Download from: https://ollama.com/download
    echo.
    echo  After installing, open a terminal and run:
    echo    ollama pull gemma3:4b
    echo.
) else (
    echo  [OK] Ollama found
)

REM Check ExifTool
exiftool -ver >nul 2>&1
if errorlevel 1 (
    echo  [WARNING] ExifTool not installed (needed to write metadata^)
    echo  Download from: https://exiftool.org
    echo  Extract exiftool.exe to a folder in your PATH
) else (
    echo  [OK] ExifTool found
)

REM Set up virtual environment
if not exist "venv" (
    echo.
    echo Setting up Python environment...
    %PYTHON% -m venv venv
)

REM Activate and install
call venv\Scripts\activate.bat
pip install -q --upgrade pip
pip install -q -r requirements.txt
echo  [OK] Dependencies installed

REM Launch
echo.
echo Launching PhotoScribe...
echo.
python photoscribe.py
