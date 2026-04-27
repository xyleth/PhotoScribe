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

MIN_PY="3.10"
MAX_PY="3.13"

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

# ── Find a compatible Python (3.10-3.13) ──
PYTHON=""
PYTHON_VERSION=""

check_python_version() {
    local py_cmd="$1"
    if ! command -v "$py_cmd" &>/dev/null; then
        return 1
    fi
    local ver
    ver=$("$py_cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null) || return 1
    local major minor
    major=$(echo "$ver" | cut -d. -f1)
    minor=$(echo "$ver" | cut -d. -f2)
    local min_minor max_minor
    min_minor=$(echo "$MIN_PY" | cut -d. -f2)
    max_minor=$(echo "$MAX_PY" | cut -d. -f2)

    if [ "$major" -eq 3 ] && [ "$minor" -ge "$min_minor" ] && [ "$minor" -le "$max_minor" ]; then
        PYTHON="$py_cmd"
        PYTHON_VERSION="$ver"
        return 0
    fi
    return 1
}

# Try specific versions first (prefer newest compatible)
for v in 3.13 3.12 3.11 3.10; do
    if check_python_version "python$v"; then
        break
    fi
done

# Fall back to python3 / python
if [ -z "$PYTHON" ]; then
    check_python_version "python3" || check_python_version "python" || true
fi

if [ -z "$PYTHON" ]; then
    if command -v python3 &>/dev/null; then
        BAD_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
        echo -e "${RED}✗ Python $BAD_VER found, but PhotoScribe requires Python ${MIN_PY}-${MAX_PY}.${NC}"
        echo ""
        if [ "$OS" = "macos" ]; then
            echo "  Install a compatible version with Homebrew:"
            echo "    brew install python@3.13"
            echo ""
            echo "  Then run this script again."
        else
            echo "  Install a compatible version:"
            echo "    sudo apt install python3.13 python3.13-venv"
            echo ""
            echo "  Then run this script again."
        fi
    else
        echo -e "${RED}✗ Python 3 not found.${NC}"
        if [ "$OS" = "macos" ]; then
            echo "  Install with: brew install python@3.13"
            echo "  Or download from: https://www.python.org/downloads/"
        else
            echo "  Install with: sudo apt install python3 python3-venv python3-pip"
        fi
    fi
    exit 1
fi

echo -e "${GREEN}✓${NC} Python $PYTHON_VERSION found ($PYTHON)"

# ── Check Ollama ──
if command -v ollama &>/dev/null; then
    echo -e "${GREEN}✓${NC} Ollama found"

    if curl -s http://localhost:11434/api/tags &>/dev/null; then
        echo -e "${GREEN}✓${NC} Ollama is running"

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

# If venv exists but was built with a different Python, rebuild it
if [ -d "$VENV_DIR" ]; then
    VENV_PY_VER=$("$VENV_DIR/bin/python" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "unknown")
    if [ "$VENV_PY_VER" != "$PYTHON_VERSION" ]; then
        echo -e "${YELLOW}⚠${NC} Existing venv uses Python $VENV_PY_VER, rebuilding with $PYTHON_VERSION..."
        rm -rf "$VENV_DIR"
    fi
fi

if [ ! -d "$VENV_DIR" ]; then
    echo ""
    echo "Setting up Python environment..."
    $PYTHON -m venv "$VENV_DIR"
    echo -e "${GREEN}✓${NC} Virtual environment created (Python $PYTHON_VERSION)"
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
