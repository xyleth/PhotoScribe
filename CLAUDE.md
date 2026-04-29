# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

PhotoScribe is a single-file PySide6 desktop app that uses a local Ollama vision model to generate IPTC/XMP metadata (title, caption, keywords) for photographs and writes it back to the file via ExifTool. Everything runs locally — no cloud calls.

## Run / install

```bash
./install.sh              # macOS/Linux: checks deps, builds venv, installs, launches
install.bat               # Windows equivalent
python photoscribe.py     # direct launch once venv is active
```

The install scripts pin Python to **3.10–3.13** (PySide6 and rawpy do not yet support 3.14). If `venv/` was built with a different minor version, `install.sh` deletes and rebuilds it. Manual env setup uses stdlib `venv` + `pip` (not `uv`) to match what the install scripts produce — keep that consistent so contributors following the README get the same environment.

There is no test suite, no linter config, and no CI in this repo. "Test before committing" means launching the app and exercising the affected flow manually.

## External runtime dependencies

The Python deps in `requirements.txt` are not the whole picture. The app shells out to two external systems:

- **Ollama** — HTTP API, default `http://localhost:11434`, configurable in the Settings tab. The app calls `/api/tags` to list models and `/api/chat` (with `stream: false`, `think: false`, `temperature: 0.3`) to generate. Gemma 4 needs Ollama ≥ 0.20.0. A remote Ollama is supported (set `OLLAMA_HOST=0.0.0.0` on the server).
- **ExifTool** — invoked via `subprocess.run(["exiftool", ...])` in `MetadataWriter`. Despite `PyExifTool` being in `requirements.txt`, the code does not use it; it builds an argv directly. If you change metadata writing, edit `MetadataWriter.write_metadata` and keep IPTC + XMP + EXIF:ImageDescription in sync (the "belt and braces" comment is intentional — different DAM tools read different fields). `MetadataWriter.read_existing_metadata` is the read-side counterpart, used to back the "skip existing" and "append keywords" modes — it parses `exiftool -j` output and silently returns empty values on any failure (so transient exiftool errors look identical to "field is empty").

Missing external tools degrade gracefully: the app launches, logs a warning, and disables the affected features (write-to-file needs ExifTool, RAW decoding needs `rawpy`).

## Architecture

Everything lives in `photoscribe.py` (~1700 lines). The structure, in order:

1. **`SUPPORTED_EXTENSIONS` / `RAW_EXTENSIONS`** — extension allowlists used by both the drop zone filter and the RAW-vs-Pillow branch in `OllamaWorker._encode_image`. Add new formats in both sets when relevant.
2. **`PhotoMetadata` / `PhotoItem`** — dataclasses. `PhotoItem.status` is one of `pending | processing | done | error` and drives both the table icons (`StatusDot`) and the skip-if-done logic in the worker.
3. **`OllamaWorker(QThread)`** — runs the whole batch on one background thread, emitting `progress`, `result`, `finished_all`, and `log_message` signals. Image encoding resizes to max 1024px JPEG before base64 — the model never sees the full-resolution file. RAW files go through `rawpy.postprocess(half_size=True, use_camera_wb=True)`. The model is asked to return strict JSON; the worker strips markdown fences and slices `{...}` defensively before `json.loads`.
4. **`MetadataWriter`** — static methods only. `check_exiftool()` is called at startup; `write_metadata(filepath, metadata, backup=True, append_keywords=False, skip_existing=False)` is called per-file from the UI thread (synchronous, 30s timeout each). When `append_keywords=False`, the replace path runs a *separate* `exiftool` subprocess to clear `IPTC:Keywords=` / `XMP:Subject=` before the main write — so two process spawns per file in the default mode.
5. **UI: `DropZone`, `StatusDot`, `STYLESHEET`** — the dark theme is a single Qt stylesheet string with named object IDs (`primaryBtn`, `dangerBtn`, `writeBtn`, `exportBtn`). To restyle a button, set `setObjectName(...)` rather than inline styles.
6. **`PhotoScribe(QMainWindow)`** — the main window holds essentially all app state (`self.photos`, `self.worker`, `QSettings`-backed preferences) and wires every signal. It is a known god object (~1000 lines); when adding features, prefer extending an existing `_method` over splitting the class — the rest of the file assumes everything hangs off this one window.

State flow: drop/browse → `_on_files_dropped` builds `PhotoItem`s → `_start_processing` constructs `OllamaWorker` with the current prompt + context + keyword vocabulary → worker emits per-photo results → `_on_result` mutates `PhotoItem.metadata` and refreshes both tables → user reviews/edits in the Results tab → `_write_metadata` invokes `MetadataWriter` per file.

Settings persist via `QSettings("PhotoScribe", "PhotoScribe")` (Ollama URL, prompt, context fields, keyword vocabulary, `create_backup`, `append_keywords`, `skip_existing`). The "Backups" checkbox toggles the `-overwrite_original` ExifTool flag — when enabled, ExifTool leaves `*_original` files next to the originals (already in `.gitignore`). The two write-mode checkboxes ("Append keywords to existing" and "Skip title/caption if file already has them") replaced the older single "Overwrite existing IPTC metadata" toggle and are wired through to `MetadataWriter.write_metadata` keyword args.

## When editing

- **Prompt construction lives in `OllamaWorker._build_prompt`.** The trailing JSON-format instruction is load-bearing — the response parser depends on the model returning a single JSON object. Keep that block intact when tweaking prompts or presets.
- **Adding a RAW format**: add the extension to both `SUPPORTED_EXTENSIONS` and `RAW_EXTENSIONS`. The `rawpy` branch handles all of them uniformly.
- **Adding a metadata field**: extend `PhotoMetadata`, the JSON schema in the prompt, the parser in `OllamaWorker.run`, the detail editor in `_load_detail` / `_on_detail_edited`, and `MetadataWriter.write_metadata` (IPTC + XMP + EXIF as appropriate). If the field should respect "skip existing", also extend `MetadataWriter.read_existing_metadata` to read it and gate the write on the existing value, mirroring how title/caption are handled.
