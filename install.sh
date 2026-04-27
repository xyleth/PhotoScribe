#!/bin/bash
# PhotoScribe - Install & Launch Script
# Works on macOS and Linux (Debian/Ubuntu)

set -e

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No colour

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo -e "${BOLD}📷 PhotoScribe${NC}"
echo -e "AI-powered photo metadata generator"
echo ""

# ── Detect OS ──
OS="unknown"
if [[ "$OSTYPE" == "darwin"* ]]; then
    OS="macos"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS="linux"
fi

# ── Check Python ──
PYTHON=""
if command -v python3 &>/dev/null; then
    PYTHON="python3"
elif command -v python &>/dev/null; then
    PYTHON="python"
fi

if [ -z "$PYTHON" ]; then
    echo -e "${RED}✗ Python 3 not found.${NC}"
    if [ "$OS" = "macos" ]; then
        echo "  Install with: brew install python3"
        echo "  Or download from: https://www.python.org/downloads/"
    else
        echo "  Install with: sudo apt install python3 python3-venv python3-pip"
    fi
    exit 1
fi

PY_VERSION=$($PYTHON --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
echo -e "${GREEN}✓${NC} Python $PY_VERSION found"

# ── Check Ollama ──
if command -v ollama &>/dev/null; then
    echo -e "${GREEN}✓${NC} Ollama found"

    # Check if Ollama is running
    if curl -s http://localhost:11434/api/tags &>/dev/null; then
        echo -e "${GREEN}✓${NC} Ollama is running"

        # Check for vision models
        MODELS=$(curl -s http://localhost:11434/api/tags | grep -oE '"name":"[^"]*"' | sed 's/"name":"//;s/"//')
        if echo "$MODELS" | grep -qi "gemma3"; then
            echo -e "${GREEN}✓${NC} Vision model found"
        else
            echo -e "${YELLOW}⚠${NC} No Gemma 3 model found. Recommended: ollama pull gemma3:4b"
            echo "  For best results: ollama pull gemma3:12b"
        fi
    else
        echo -e "${YELLOW}⚠${NC} Ollama installed but not running. Start it with: ollama serve"
    fi
else
    echo -e "${YELLOW}⚠${NC} Ollama not installed."
    echo ""
    echo "  PhotoScribe needs Ollama to run AI models locally."
    echo "  Install from: https://ollama.com/download"
    echo ""
    echo "  After installing Ollama, pull a vision model:"
    echo "    ollama pull gemma3:4b    (smaller, faster, ~3GB)"
    echo "    ollama pull gemma3:12b   (better quality, ~8GB)"
    echo ""
    read -p "  Continue setup anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# ── Check ExifTool ──
if command -v exiftool &>/dev/null; then
    echo -e "${GREEN}✓${NC} ExifTool found"
else
    echo -e "${YELLOW}⚠${NC} ExifTool not installed (needed to write metadata to files)"
    if [ "$OS" = "macos" ]; then
        read -p "  Install via Homebrew? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            if command -v brew &>/dev/null; then
                brew install exiftool
                echo -e "${GREEN}✓${NC} ExifTool installed"
            else
                echo -e "${RED}✗${NC} Homebrew not found. Install ExifTool manually:"
                echo "  https://exiftool.org"
            fi
        fi
    else
        read -p "  Install via apt? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            sudo apt install -y libimage-exiftool-perl
            echo -e "${GREEN}✓${NC} ExifTool installed"
        fi
    fi
fi

# ── Set up Python virtual environment ──
VENV_DIR="$SCRIPT_DIR/venv"

if [ ! -d "$VENV_DIR" ]; then
    echo ""
    echo "Setting up Python environment..."
    $PYTHON -m venv "$VENV_DIR"
    echo -e "${GREEN}✓${NC} Virtual environment created"
fi

# Activate venv
source "$VENV_DIR/bin/activate"

# Install/update dependencies
echo "Installing dependencies..."
pip install -q --upgrade pip
pip install -q -r "$SCRIPT_DIR/requirements.txt"
echo -e "${GREEN}✓${NC} Dependencies installed"

# ── Launch ──
echo ""
echo -e "${BOLD}Launching PhotoScribe...${NC}"
echo ""
python "$SCRIPT_DIR/photoscribe.py"
