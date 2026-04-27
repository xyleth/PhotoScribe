@echo off
REM PhotoScribe - Install & Launch Script for Windows
REM Requires Python 3.10+ installed and in PATH

echo.
echo  PhotoScribe
echo  AI-powered photo metadata generator
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python 3 not found.
    echo  Download from: https://www.python.org/downloads/
    echo  IMPORTANT: Check "Add Python to PATH" during installation.
    pause
    exit /b 1
)
echo  [OK] Python found

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
    python -m venv venv
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
