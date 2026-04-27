@echo off
setlocal enabledelayedexpansion
REM PhotoScribe - Install & Launch Script for Windows
REM Requires Python 3.10-3.13 (64-bit) installed and in PATH

echo.
echo  PhotoScribe
echo  AI-powered photo metadata generator
echo.

REM ── Find compatible Python ──
set "PYTHON="
set "PY_VER="

REM Try py launcher first (most reliable on Windows)
where py >nul 2>&1
if not errorlevel 1 (
    for %%V in (3.13 3.12 3.11 3.10) do (
        if not defined PYTHON (
            py -%%V --version >nul 2>&1
            if not errorlevel 1 (
                set "PYTHON=py -%%V"
                set "PY_VER=%%V"
            )
        )
    )
)

REM Try versioned python commands
if not defined PYTHON (
    for %%V in (3.13 3.12 3.11 3.10) do (
        if not defined PYTHON (
            where python%%V >nul 2>&1
            if not errorlevel 1 (
                set "PYTHON=python%%V"
                set "PY_VER=%%V"
            )
        )
    )
)

REM Try generic python and check version
if not defined PYTHON (
    where python >nul 2>&1
    if not errorlevel 1 (
        for /f "usebackq delims=" %%A in (`python -c "import sys; v=sys.version_info; print(f'{v.major}.{v.minor}') if 10<=v.minor<=13 and v.major==3 else print('BAD')" 2^>nul`) do (
            if "%%A" NEQ "BAD" (
                set "PYTHON=python"
                set "PY_VER=%%A"
            )
        )
    )
)

if not defined PYTHON (
    echo  [ERROR] No compatible Python found. Need Python 3.10-3.13 ^(64-bit^).
    echo.
    echo  Download Python 3.13 ^(64-bit^) from:
    echo  https://www.python.org/ftp/python/3.13.0/python-3.13.0-amd64.exe
    echo.
    echo  IMPORTANT: Tick "Add python.exe to PATH" during installation.
    echo  The filename must contain "amd64" ^(this means 64-bit, works on Intel too^).
    echo  Do NOT install Python 3.14 - it is not yet supported.
    echo.
    pause
    exit /b 1
)

REM Check if 64-bit
for /f "usebackq delims=" %%A in (`%PYTHON% -c "import struct; print(struct.calcsize('P') * 8)" 2^>nul`) do set "PY_BITS=%%A"
if "%PY_BITS%" NEQ "64" (
    echo  [ERROR] Python %PY_VER% is installed but it's %PY_BITS%-bit.
    echo  PhotoScribe requires 64-bit Python.
    echo.
    echo  Uninstall the current Python, then download the 64-bit version:
    echo  https://www.python.org/ftp/python/3.13.0/python-3.13.0-amd64.exe
    echo.
    pause
    exit /b 1
)

echo  [OK] Python %PY_VER% ^(64-bit^) found

REM ── Check Ollama ──
where ollama >nul 2>&1
if errorlevel 1 (
    echo  [WARNING] Ollama not installed.
    echo.
    echo  PhotoScribe needs Ollama to run AI models locally.
    echo  Download from: https://ollama.com/download
    echo.
    echo  After installing, open a new command prompt and run:
    echo    ollama pull gemma3:12b
    echo.
) else (
    echo  [OK] Ollama found
)

REM ── Check ExifTool ──
where exiftool >nul 2>&1
if errorlevel 1 (
    echo  [WARNING] ExifTool not installed ^(needed to write metadata to files^)
    echo.
    echo  To install ExifTool on Windows:
    echo    1. Download "Windows Executable" from https://exiftool.org
    echo    2. Extract the zip
    echo    3. Rename "exiftool(-k).exe" to "exiftool.exe"
    echo    4. Move it to C:\Windows\
    echo.
    echo  PhotoScribe will still run without it, but you won't be able
    echo  to write metadata directly to files ^(CSV export still works^).
    echo.
) else (
    echo  [OK] ExifTool found
)

REM ── Set up virtual environment ──
if exist "venv" (
    REM Check if existing venv matches our Python
    venv\Scripts\python.exe -c "import sys; v=sys.version_info; exit(0 if f'{v.major}.{v.minor}'=='%PY_VER%' else 1)" 2>nul
    if errorlevel 1 (
        echo  [INFO] Rebuilding venv for Python %PY_VER%...
        rmdir /s /q venv
    )
)

if not exist "venv" (
    echo.
    echo  Setting up Python environment...
    %PYTHON% -m venv venv
    if errorlevel 1 (
        echo  [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo  [OK] Virtual environment created
)

REM Activate
call venv\Scripts\activate.bat

REM Install dependencies
echo  Installing dependencies...
pip install -q --upgrade pip 2>nul
pip install -r requirements.txt 2>nul
if errorlevel 1 (
    echo.
    echo  [ERROR] Failed to install dependencies.
    echo  This usually means your Python is the wrong version or 32-bit.
    echo  Check with: python -c "import struct, sys; print(f'{sys.version_info.major}.{sys.version_info.minor}, {struct.calcsize('P') * 8}-bit')"
    echo  You need 64-bit Python 3.10-3.13.
    echo.
    pause
    exit /b 1
)
echo  [OK] Dependencies installed

REM ── Launch ──
echo.
echo  Launching PhotoScribe...
echo.
python photoscribe.py
