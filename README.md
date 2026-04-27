# PhotoScribe

AI-powered photo metadata generator that runs entirely on your machine. Uses local Ollama models to analyse your photographs and write title, caption, and keywords directly to IPTC/XMP metadata.

No cloud services. No subscriptions. No data leaves your computer.

![PhotoScribe Screenshot](screenshot.png)

## What it does

1. **Drop** photos into the app (drag and drop or browse)
2. **Set context** (location, event, photographer) to help the AI
3. **Generate** titles, captions, and keywords using a local vision model
4. **Review and edit** everything before committing
5. **Write** IPTC + XMP metadata directly to your files

Metadata is written to both IPTC and embedded XMP, so Lightroom Classic, Capture One, Photo Mechanic, Bridge, and every other cataloguing tool picks it up on import.

## Supported formats

**Standard:** JPEG, TIFF, PNG, WebP

**RAW:** CR2, CR3 (Canon), NEF (Nikon), ARW (Sony), ORF (Olympus/OM System), RAF (Fujifilm), RW2 (Panasonic), PEF (Pentax), DNG, and more

## Requirements

You need three things installed before running PhotoScribe.

### 1. Python 3.10-3.13

> **⚠ Do NOT install Python 3.14.** Key dependencies (PySide6, rawpy) don't support it yet. You need 3.13 or earlier.

**macOS:**
```bash
brew install python@3.13
```

**Windows:**

Download the **64-bit** installer for Python 3.13 directly:

👉 **[Download Python 3.13 (64-bit) for Windows](https://www.python.org/ftp/python/3.13.0/python-3.13.0-amd64.exe)**

During installation:
- ✅ Tick **"Add python.exe to PATH"** (bottom of the first screen, easy to miss)
- The `amd64` in the filename means 64-bit, it works on both Intel and AMD processors
- Do NOT use the Microsoft Store version, and do not install from the python.org downloads page without checking the filename contains `amd64`

**Linux:**
```bash
sudo apt install python3 python3-venv python3-pip
```

### 2. Ollama (runs the AI model locally)

Download and install from **[ollama.com/download](https://ollama.com/download)**.

After installing, open a terminal (Terminal on Mac, Command Prompt on Windows) and pull a vision model:

```
ollama pull gemma3:12b
```

This downloads ~8GB. If your machine has less than 8GB of RAM, use the smaller model instead:

```
ollama pull gemma3:4b
```

Ollama runs in the background automatically after installation. On macOS you'll see it in the menu bar. On Windows it runs as a system tray app.

### 3. ExifTool (writes metadata to files)

ExifTool is needed to write the generated metadata into your photo files. PhotoScribe will work without it (you can still generate and export to CSV), but you won't be able to write directly to files.

**macOS:**
```bash
brew install exiftool
```

**Windows:**
1. Download the **"Windows Executable"** zip from [exiftool.org](https://exiftool.org)
2. Extract the zip
3. Inside you'll find a file called `exiftool(-k).exe`
4. Rename it to `exiftool.exe` (remove the `(-k)` part)
5. Move it to `C:\Windows\` so it's available system-wide

**Linux:**
```bash
sudo apt install libimage-exiftool-perl
```

## Quick start

### macOS / Linux

```bash
git clone https://github.com/repomonkey/PhotoScribe.git
cd PhotoScribe
chmod +x install.sh
./install.sh
```

The install script checks all dependencies, finds a compatible Python version (3.10-3.13), sets up a virtual environment, installs packages, and launches the app. Run `./install.sh` again any time to launch.

### Windows

**Option A: Download ZIP (recommended if you don't have Git)**

1. Go to **[github.com/repomonkey/PhotoScribe](https://github.com/repomonkey/PhotoScribe)**
2. Click the green **"Code"** button, then **"Download ZIP"**
3. Extract the ZIP to a folder (e.g. `C:\Users\YourName\PhotoScribe`)
4. Open Command Prompt, navigate to the folder, and run:

```cmd
cd C:\Users\YourName\PhotoScribe\PhotoScribe-main
install.bat
```

**Option B: Git clone**

```cmd
git clone https://github.com/repomonkey/PhotoScribe.git
cd PhotoScribe
install.bat
```

### Manual setup

If you prefer to do it yourself:

```bash
git clone https://github.com/repomonkey/PhotoScribe.git
cd PhotoScribe
python3 -m venv venv
source venv/bin/activate        # macOS/Linux
# venv\Scripts\activate.bat     # Windows
pip install -r requirements.txt
python photoscribe.py
```

## Features

- **Drag and drop** photos or browse files/folders
- **RAW file support** via rawpy (CR2, CR3, NEF, ARW, ORF, RAF, RW2, PEF, DNG, and more)
- **Model selection** with any vision model available in your Ollama instance
- **Customisable prompts** with presets (Landscape, Event, Product)
- **Batch context** for location, event, photographer, date/time
- **Keyword vocabulary** for consistent tagging across your catalogue
- **Review and edit** all generated metadata before writing
- **IPTC + XMP** metadata written directly to files via ExifTool
- **Backup option** with persistent settings
- **CSV export** for spreadsheet review
- **Dark UI** because photographers have standards

## Tips

- **Model size matters.** The 12b model produces noticeably better captions than 4b, which in turn beats 1b significantly. Use the biggest model your hardware can handle.
- **GPU matters on Windows.** If you have an NVIDIA GPU with 12GB+ VRAM, the 12b model will run entirely on the GPU and be very fast. With 8GB VRAM it'll partially offload to CPU and be slower but still usable.
- **Set batch context.** The model produces much better results when it knows the location and event. Don't skip this.
- **Use the keyword vocabulary** if you need consistent terms across your catalogue.
- **Review before writing.** The AI is good but not infallible. The results panel lets you edit everything before it touches your files.
- **Backups** are on by default. Once you trust the workflow, you can disable them in Options.

## How it works

PhotoScribe sends a resized JPEG version of your photo (max 1024px) to your local Ollama instance along with your prompt and context. The model analyses the image and returns structured JSON with title, caption, and keywords. Nothing is uploaded anywhere: the model runs on your CPU/GPU.

When you write metadata, PhotoScribe uses ExifTool to embed IPTC and XMP data directly into your files. This is the same approach used by professional DAM tools and ensures compatibility with every major photo cataloguing application.

## Troubleshooting

**"Cannot connect to Ollama"**
Run `ollama serve` in a terminal. On macOS, Ollama may already be running as a menu bar app. On Windows, check your system tray (bottom-right of the taskbar).

**"exiftool not found"**
Install ExifTool using the instructions above. On macOS, `brew install exiftool` is the easiest path. On Windows, make sure you renamed the file to `exiftool.exe` and placed it in `C:\Windows\`.

**RAW files not loading**
Make sure `rawpy` is installed: `pip install rawpy`. The install script handles this automatically.

**App won't launch on macOS**
If you get a security warning, go to System Settings > Privacy & Security and allow the app to run.

**Slow generation**
Larger models take longer. On a Mac with Apple Silicon, the 12b model typically processes a photo in 5-15 seconds. On Windows with a GPU, speed depends on how much of the model fits in VRAM. If it's very slow, try `gemma3:4b`.

**"No matching distribution found" or PySide6/rawpy errors during install**
This means your Python version is either too new (3.14) or 32-bit. Check with:
```
python -c "import struct, sys; print(f'Python {sys.version_info.major}.{sys.version_info.minor}, {struct.calcsize(\"P\") * 8}-bit')"
```
You need **64-bit Python 3.10-3.13**. If you have the wrong version, uninstall it and download the correct one using the direct link in the Requirements section above. Then delete the venv and try again:
```bash
# macOS/Linux
rm -rf venv
./install.sh

# Windows
rmdir /s /q venv
install.bat
```

**"permission denied: ./install.sh"**
After cloning on macOS/Linux, you may need to make the script executable:
```bash
chmod +x install.sh
```

**Windows: "python is not recognized"**
You didn't tick "Add python.exe to PATH" during installation. Either reinstall Python with that option ticked, or add it manually via System Settings > Environment Variables.

## Licence

MIT

## Credits

Built by [Andy Hutchinson](https://andyhutchinson.com.au) | [YouTube](https://youtube.com/@Andyhutchinson) | [Substack](https://andyhutchinson.substack.com)

PhotoScribe uses [Ollama](https://ollama.com) for local AI inference and [ExifTool](https://exiftool.org) by Phil Harvey for metadata operations.
