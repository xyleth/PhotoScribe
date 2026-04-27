#!/usr/bin/env python3
"""
PhotoScribe - AI-Powered Photo Metadata Generator
Uses local Ollama models (Gemma 3) to analyse photographs and generate
title, caption, and keywords, then writes them directly to IPTC/XMP metadata.

Requires: Python 3.10+, PySide6, Pillow, requests, rawpy, exiftool (system)
"""

import sys
import os
import json
import base64
import threading
import subprocess
import shutil
from pathlib import Path
from io import BytesIO
from dataclasses import dataclass, field
from typing import Optional

import requests
from PIL import Image

# RAW support (optional but recommended)
try:
    import rawpy
    HAS_RAWPY = True
except ImportError:
    HAS_RAWPY = False
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QTextEdit, QLineEdit, QComboBox,
    QProgressBar, QScrollArea, QFrame, QSplitter, QGroupBox, QCheckBox,
    QFileDialog, QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QTabWidget, QSpinBox, QMenu, QToolButton, QSizePolicy, QPlainTextEdit,
    QAbstractItemView, QStyledItemDelegate, QStyle
)
from PySide6.QtCore import (
    Qt, Signal, QThread, QSize, QMimeData, QTimer, QSettings, QUrl
)
from PySide6.QtGui import (
    QPixmap, QImage, QDragEnterEvent, QDropEvent, QFont, QColor,
    QPalette, QIcon, QAction, QPainter, QFontDatabase
)


# ─────────────────────────────────────────────────────────
# Supported file formats
# ─────────────────────────────────────────────────────────

SUPPORTED_EXTENSIONS = {
    # Standard image formats
    ".jpg", ".jpeg", ".tif", ".tiff", ".png", ".webp",
    # RAW formats
    ".dng", ".cr2", ".cr3", ".nef", ".arw", ".orf", ".raf",
    ".rw2", ".pef", ".srw", ".x3f", ".3fr", ".mrw", ".nrw",
    ".raw", ".sr2", ".srf", ".erf",
}

RAW_EXTENSIONS = {
    ".cr2", ".cr3", ".nef", ".arw", ".orf", ".raf", ".rw2",
    ".dng", ".pef", ".srw", ".x3f", ".3fr", ".mrw", ".nrw",
    ".raw", ".sr2", ".srf", ".erf",
}

# ─────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────

@dataclass
class PhotoMetadata:
    title: str = ""
    caption: str = ""
    keywords: list = field(default_factory=list)

@dataclass
class PhotoItem:
    filepath: str
    filename: str
    thumbnail: Optional[QPixmap] = None
    metadata: Optional[PhotoMetadata] = None
    status: str = "pending"  # pending, processing, done, error
    error_msg: str = ""


# ─────────────────────────────────────────────────────────
# Ollama API worker thread
# ─────────────────────────────────────────────────────────

class OllamaWorker(QThread):
    """Processes photos through Ollama in a background thread."""
    progress = Signal(int, str)        # index, status
    result = Signal(int, object)       # index, PhotoMetadata or error string
    finished_all = Signal()
    log_message = Signal(str)

    def __init__(self, photos, model, prompt, context, ollama_url, keywords_list=None):
        super().__init__()
        self.photos = photos
        self.model = model
        self.prompt = prompt
        self.context = context
        self.ollama_url = ollama_url
        self.keywords_list = keywords_list or []
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def _encode_image(self, filepath):
        """Load and resize image for the model. Handles RAW files via rawpy."""
        try:
            ext = Path(filepath).suffix.lower()

            if ext in RAW_EXTENSIONS:
                if not HAS_RAWPY:
                    raise RuntimeError(
                        f"rawpy not installed. Run: pip install rawpy"
                    )
                # Convert RAW to RGB array via LibRaw
                with rawpy.imread(filepath) as raw:
                    rgb = raw.postprocess(
                        use_camera_wb=True,
                        half_size=True,  # Faster, plenty for AI analysis
                        no_auto_bright=False,
                    )
                img = Image.fromarray(rgb)
            else:
                img = Image.open(filepath)
                img = img.convert("RGB")

            # Resize to max 1024px on longest side for efficiency
            max_dim = 1024
            if max(img.size) > max_dim:
                ratio = max_dim / max(img.size)
                new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
                img = img.resize(new_size, Image.LANCZOS)
            buffer = BytesIO()
            img.save(buffer, format="JPEG", quality=85)
            return base64.b64encode(buffer.getvalue()).decode("utf-8")
        except Exception as e:
            raise RuntimeError(f"Failed to load image: {e}")

    def _build_prompt(self):
        """Construct the full prompt with context."""
        parts = []

        if self.context.strip():
            parts.append(f"Context for this photo: {self.context.strip()}")

        parts.append(self.prompt.strip())

        if self.keywords_list:
            vocab = ", ".join(self.keywords_list[:200])
            parts.append(
                f"\nWhen generating keywords, prefer terms from this vocabulary "
                f"where applicable: {vocab}"
            )

        parts.append(
            "\nRespond ONLY with valid JSON in this exact format, no other text:\n"
            '{"title": "Short descriptive title", '
            '"caption": "Detailed description of the image in 1-3 sentences", '
            '"keywords": ["keyword1", "keyword2", "keyword3"]}'
        )
        return "\n\n".join(parts)

    def run(self):
        full_prompt = self._build_prompt()

        for i, photo in enumerate(self.photos):
            if self._cancelled:
                break
            if photo.status == "done":
                continue

            self.progress.emit(i, "processing")
            self.log_message.emit(f"Processing: {photo.filename}")

            try:
                img_b64 = self._encode_image(photo.filepath)

                payload = {
                    "model": self.model,
                    "messages": [
                        {
                            "role": "user",
                            "content": full_prompt,
                            "images": [img_b64],
                        }
                    ],
                    "stream": False,
                    "options": {
                        "temperature": 0.3,
                        "num_predict": 1024,
                    },
                    "think": False,
                }

                self.log_message.emit(f"Sending to {self.model}...")
                resp = requests.post(
                    f"{self.ollama_url}/api/chat",
                    json=payload,
                    timeout=180
                )
                resp.raise_for_status()
                resp_json = resp.json()
                response_text = resp_json.get("message", {}).get("content", "")
                self.log_message.emit(f"Response received ({len(response_text)} chars)")

                # Parse JSON from response (handle markdown fences)
                cleaned = response_text.strip()
                if cleaned.startswith("```"):
                    lines = cleaned.split("\n")
                    lines = [l for l in lines if not l.strip().startswith("```")]
                    cleaned = "\n".join(lines).strip()

                # Try to find JSON object in response
                start = cleaned.find("{")
                end = cleaned.rfind("}") + 1
                if start >= 0 and end > start:
                    cleaned = cleaned[start:end]

                data = json.loads(cleaned)
                meta = PhotoMetadata(
                    title=data.get("title", "").strip(),
                    caption=data.get("caption", "").strip(),
                    keywords=[k.strip() for k in data.get("keywords", []) if k.strip()]
                )
                self.result.emit(i, meta)
                self.log_message.emit(f"Done: {photo.filename}")

            except json.JSONDecodeError as e:
                self.log_message.emit(f"JSON parse error: {e}\nRaw: {response_text[:300]}")
                self.result.emit(i, f"Failed to parse model response: {e}")
            except requests.exceptions.ConnectionError:
                self.log_message.emit("Connection failed. Is Ollama running?")
                self.result.emit(i, "Cannot connect to Ollama. Is it running? (ollama serve)")
            except Exception as e:
                self.log_message.emit(f"Error: {e}")
                self.result.emit(i, str(e))

        self.finished_all.emit()


# ─────────────────────────────────────────────────────────
# Metadata writer (ExifTool)
# ─────────────────────────────────────────────────────────

class MetadataWriter:
    """Writes IPTC and XMP metadata using exiftool."""

    @staticmethod
    def check_exiftool():
        """Check if exiftool is available."""
        return shutil.which("exiftool") is not None

    @staticmethod
    def write_metadata(filepath, metadata: PhotoMetadata, backup=True):
        """Write title, caption, keywords to file via exiftool."""
        args = ["exiftool"]

        if not backup:
            args.append("-overwrite_original")

        # IPTC fields
        args.append(f"-IPTC:ObjectName={metadata.title}")
        args.append(f"-IPTC:Caption-Abstract={metadata.caption}")

        # Clear existing keywords first, then add new ones
        args.append("-IPTC:Keywords=")
        for kw in metadata.keywords:
            args.append(f"-IPTC:Keywords+={kw}")

        # XMP embedded (belt and braces)
        args.append(f"-XMP:Title={metadata.title}")
        args.append(f"-XMP:Description={metadata.caption}")
        args.append("-XMP:Subject=")
        for kw in metadata.keywords:
            args.append(f"-XMP:Subject+={kw}")

        # EXIF description as well
        args.append(f"-EXIF:ImageDescription={metadata.caption}")

        args.append(filepath)

        result = subprocess.run(args, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(f"exiftool error: {result.stderr}")
        return True


# ─────────────────────────────────────────────────────────
# Stylesheet
# ─────────────────────────────────────────────────────────

STYLESHEET = """
QMainWindow {
    background-color: #1a1a1e;
}
QWidget {
    color: #e0e0e0;
    font-family: 'Helvetica Neue', 'Segoe UI', sans-serif;
    font-size: 13px;
}
QGroupBox {
    font-weight: 600;
    font-size: 12px;
    letter-spacing: 0.5px;
    text-transform: uppercase;
    color: #a0a0a0;
    border: 1px solid #2a2a30;
    border-radius: 8px;
    margin-top: 12px;
    padding: 12px 12px 10px 12px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    margin-left: 8px;
}
QPushButton {
    background-color: #2a2a30;
    border: 1px solid #3a3a42;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 500;
    color: #e0e0e0;
    min-height: 20px;
}
QPushButton:hover {
    background-color: #35353d;
    border-color: #e8a23a;
}
QPushButton:pressed {
    background-color: #e8a23a;
    color: #1a1a1e;
}
QPushButton:disabled {
    background-color: #222226;
    color: #555;
    border-color: #2a2a30;
}
QPushButton#primaryBtn {
    background-color: #e8a23a;
    color: #1a1a1e;
    font-weight: 700;
    border: none;
}
QPushButton#primaryBtn:hover {
    background-color: #f0b04a;
}
QPushButton#primaryBtn:disabled {
    background-color: #5a4a20;
    color: #888;
}
QPushButton#dangerBtn {
    background-color: #c0392b;
    color: #fff;
    border: none;
}
QPushButton#dangerBtn:hover {
    background-color: #e74c3c;
}
QPushButton#writeBtn {
    background-color: #27ae60;
    color: #fff;
    font-weight: 700;
    border: none;
}
QPushButton#writeBtn:hover {
    background-color: #2ecc71;
}
QPushButton#exportBtn {
    background-color: #2980b9;
    color: #fff;
    font-weight: 700;
    border: none;
}
QPushButton#exportBtn:hover {
    background-color: #3498db;
}
QPushButton#exportBtn:disabled {
    background-color: #1a3a50;
    color: #888;
}
QComboBox {
    background-color: #2a2a30;
    border: 1px solid #3a3a42;
    border-radius: 6px;
    padding: 6px 10px;
    min-height: 20px;
}
QComboBox:hover {
    border-color: #e8a23a;
}
QComboBox QAbstractItemView {
    background-color: #2a2a30;
    border: 1px solid #3a3a42;
    selection-background-color: #e8a23a;
    selection-color: #1a1a1e;
}
QComboBox::drop-down {
    border: none;
    width: 24px;
}
QLineEdit, QTextEdit, QPlainTextEdit {
    background-color: #222226;
    border: 1px solid #3a3a42;
    border-radius: 6px;
    padding: 10px 12px;
    color: #e0e0e0;
    selection-background-color: #e8a23a;
    selection-color: #1a1a1e;
}
QLineEdit {
    min-height: 22px;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border-color: #e8a23a;
}
QTableWidget {
    background-color: #1e1e22;
    border: 1px solid #2a2a30;
    border-radius: 6px;
    gridline-color: #2a2a30;
    selection-background-color: #3a3520;
}
QTableWidget::item {
    padding: 6px 8px;
    border-bottom: 1px solid #2a2a30;
}
QTableWidget::item:selected {
    background-color: #3a3520;
    color: #e8a23a;
}
QHeaderView::section {
    background-color: #222226;
    color: #a0a0a0;
    border: none;
    border-bottom: 2px solid #e8a23a;
    padding: 8px;
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
QProgressBar {
    background-color: #222226;
    border: 1px solid #2a2a30;
    border-radius: 4px;
    height: 8px;
    text-align: center;
    font-size: 10px;
}
QProgressBar::chunk {
    background-color: #e8a23a;
    border-radius: 3px;
}
QScrollArea {
    border: none;
}
QScrollBar:vertical {
    background-color: #1a1a1e;
    width: 10px;
    border: none;
}
QScrollBar::handle:vertical {
    background-color: #3a3a42;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background-color: #e8a23a;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QTabWidget::pane {
    border: 1px solid #2a2a30;
    border-radius: 6px;
    background-color: #1e1e22;
}
QTabBar::tab {
    background-color: #222226;
    color: #a0a0a0;
    border: 1px solid #2a2a30;
    border-bottom: none;
    padding: 8px 16px;
    margin-right: 2px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    font-weight: 500;
}
QTabBar::tab:selected {
    background-color: #1e1e22;
    color: #e8a23a;
    border-bottom: 2px solid #e8a23a;
}
QTabBar::tab:hover:!selected {
    color: #e0e0e0;
}
QCheckBox {
    spacing: 8px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid #3a3a42;
    background-color: #222226;
}
QCheckBox::indicator:checked {
    background-color: #e8a23a;
    border-color: #e8a23a;
}
QSplitter::handle {
    background-color: #2a2a30;
    width: 2px;
}
QSplitter::handle:hover {
    background-color: #e8a23a;
}
QLabel#statusLabel {
    color: #888;
    font-size: 11px;
}
QLabel#dropLabel {
    color: #666;
    font-size: 15px;
    font-weight: 300;
}
QLabel#titleLabel {
    font-family: 'Bebas Neue', 'Arial Narrow', sans-serif;
    font-size: 28px;
    font-weight: 400;
    color: #e8a23a;
    letter-spacing: 2px;
}
QLabel#subtitleLabel {
    font-size: 11px;
    color: #666;
    font-weight: 400;
    letter-spacing: 1px;
}
"""


# ─────────────────────────────────────────────────────────
# Drop zone widget
# ─────────────────────────────────────────────────────────

class DropZone(QFrame):
    files_dropped = Signal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setMinimumHeight(120)
        self.setStyleSheet("""
            DropZone {
                border: 2px dashed #3a3a42;
                border-radius: 12px;
                background-color: #1e1e22;
            }
            DropZone:hover {
                border-color: #e8a23a;
                background-color: #222226;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)

        icon_label = QLabel("📷")
        icon_label.setStyleSheet("font-size: 32px; background: transparent; border: none;")
        icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon_label)

        text_label = QLabel("Drop photos here or click Browse")
        text_label.setObjectName("dropLabel")
        text_label.setAlignment(Qt.AlignCenter)
        text_label.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(text_label)

        formats_label = QLabel("JPEG  ·  TIFF  ·  PNG  ·  RAW  ·  DNG  ·  CR2/CR3  ·  NEF  ·  ARW  ·  ORF  ·  RAF")
        formats_label.setStyleSheet(
            "color: #555; font-size: 11px; background: transparent; border: none;"
        )
        formats_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(formats_label)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet("""
                DropZone {
                    border: 2px solid #e8a23a;
                    border-radius: 12px;
                    background-color: #2a2520;
                }
            """)

    def dragLeaveEvent(self, event):
        self.setStyleSheet("""
            DropZone {
                border: 2px dashed #3a3a42;
                border-radius: 12px;
                background-color: #1e1e22;
            }
            DropZone:hover {
                border-color: #e8a23a;
                background-color: #222226;
            }
        """)

    def dropEvent(self, event: QDropEvent):
        self.setStyleSheet("""
            DropZone {
                border: 2px dashed #3a3a42;
                border-radius: 12px;
                background-color: #1e1e22;
            }
            DropZone:hover {
                border-color: #e8a23a;
                background-color: #222226;
            }
        """)
        urls = event.mimeData().urls()
        files = []
        for url in urls:
            path = url.toLocalFile()
            if os.path.isfile(path) and Path(path).suffix.lower() in SUPPORTED_EXTENSIONS:
                files.append(path)
            elif os.path.isdir(path):
                for root, dirs, fnames in os.walk(path):
                    for f in fnames:
                        fp = os.path.join(root, f)
                        if Path(fp).suffix.lower() in SUPPORTED_EXTENSIONS:
                            files.append(fp)
        if files:
            self.files_dropped.emit(files)


# ─────────────────────────────────────────────────────────
# Status indicator widget
# ─────────────────────────────────────────────────────────

class StatusDot(QLabel):
    COLOURS = {
        "pending": "#555",
        "processing": "#e8a23a",
        "done": "#27ae60",
        "error": "#c0392b",
    }

    def __init__(self, status="pending"):
        super().__init__()
        self.setFixedSize(12, 12)
        self.set_status(status)

    def set_status(self, status):
        colour = self.COLOURS.get(status, "#555")
        self.setStyleSheet(f"""
            background-color: {colour};
            border-radius: 6px;
            border: none;
        """)


# ─────────────────────────────────────────────────────────
# Main window
# ─────────────────────────────────────────────────────────

class PhotoScribe(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PhotoScribe")
        self.setMinimumSize(1100, 750)
        self.resize(1300, 850)

        self.photos: list[PhotoItem] = []
        self.worker: Optional[OllamaWorker] = None
        self.settings = QSettings("PhotoScribe", "PhotoScribe")

        self._init_ui()
        self._load_settings()
        self._check_dependencies()

    def _check_dependencies(self):
        if not MetadataWriter.check_exiftool():
            self.log("⚠ exiftool not found! Install it:")
            self.log("  macOS: brew install exiftool")
            self.log("  Linux: sudo apt install libimage-exiftool-perl")
            self.log("  Windows: https://exiftool.org")
        if not HAS_RAWPY:
            self.log("⚠ rawpy not installed. RAW file support disabled.")
            self.log("  Install with: pip install rawpy")

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(16, 12, 16, 12)
        main_layout.setSpacing(8)

        # ── Header ──
        header = QHBoxLayout()

        title_col = QVBoxLayout()
        title = QLabel("PhotoScribe")
        title.setObjectName("titleLabel")
        title_col.addWidget(title)
        subtitle = QLabel("AI-powered metadata generation using local models")
        subtitle.setObjectName("subtitleLabel")
        title_col.addWidget(subtitle)
        header.addLayout(title_col)
        header.addStretch()

        # Ollama status
        self.ollama_status = QLabel("● Checking Ollama...")
        self.ollama_status.setStyleSheet("color: #e8a23a; font-size: 12px;")
        header.addWidget(self.ollama_status)

        main_layout.addLayout(header)

        # ── Splitter: left panel + right panel ──
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(3)

        # ═══ LEFT PANEL ═══
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(8)

        # Drop zone
        self.drop_zone = DropZone()
        self.drop_zone.files_dropped.connect(self._on_files_dropped)
        left_layout.addWidget(self.drop_zone)

        # Browse + clear buttons
        btn_row = QHBoxLayout()
        browse_btn = QPushButton("Browse Files")
        browse_btn.clicked.connect(self._browse_files)
        btn_row.addWidget(browse_btn)

        browse_dir_btn = QPushButton("Browse Folder")
        browse_dir_btn.clicked.connect(self._browse_folder)
        btn_row.addWidget(browse_dir_btn)

        self.clear_btn = QPushButton("Clear All")
        self.clear_btn.setObjectName("dangerBtn")
        self.clear_btn.clicked.connect(self._clear_all)
        btn_row.addWidget(self.clear_btn)
        left_layout.addLayout(btn_row)

        # Photo list table
        self.photo_table = QTableWidget()
        self.photo_table.setColumnCount(4)
        self.photo_table.setHorizontalHeaderLabels(["", "Filename", "Status", "Title"])
        self.photo_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.photo_table.setColumnWidth(0, 16)
        self.photo_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.photo_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self.photo_table.setColumnWidth(2, 80)
        self.photo_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.photo_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.photo_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.photo_table.verticalHeader().setVisible(False)
        self.photo_table.setShowGrid(False)
        self.photo_table.setAlternatingRowColors(True)
        self.photo_table.setStyleSheet(
            self.photo_table.styleSheet() +
            "QTableWidget { alternate-background-color: #1c1c20; }"
        )
        self.photo_table.currentCellChanged.connect(self._on_photo_selected)
        left_layout.addWidget(self.photo_table, 1)

        # Photo count
        self.photo_count_label = QLabel("0 photos loaded")
        self.photo_count_label.setObjectName("statusLabel")
        left_layout.addWidget(self.photo_count_label)

        splitter.addWidget(left_panel)

        # ═══ RIGHT PANEL ═══
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(8)

        # Tabs
        tabs = QTabWidget()

        # ── Settings Tab ──
        settings_tab = QWidget()
        settings_layout = QVBoxLayout(settings_tab)
        settings_layout.setSpacing(8)

        # Model selection
        model_group = QGroupBox("Model")
        model_layout = QHBoxLayout(model_group)
        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(200)
        model_layout.addWidget(self.model_combo)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setFixedWidth(80)
        refresh_btn.clicked.connect(self._refresh_models)
        model_layout.addWidget(refresh_btn)
        model_layout.addStretch()

        # Ollama URL
        model_layout.addWidget(QLabel("URL:"))
        self.ollama_url = QLineEdit("http://localhost:11434")
        self.ollama_url.setFixedWidth(200)
        model_layout.addWidget(self.ollama_url)
        settings_layout.addWidget(model_group)

        # Prompt
        prompt_group = QGroupBox("Prompt")
        prompt_layout = QVBoxLayout(prompt_group)
        self.prompt_edit = QTextEdit()
        self.prompt_edit.setMaximumHeight(120)
        self.prompt_edit.setPlaceholderText("Enter your prompt for the AI model...")
        self.prompt_edit.setText(
            "Analyse this photograph and generate metadata for it.\n\n"
            "Title: A concise, descriptive title (5-10 words).\n"
            "Caption: A detailed description of the scene, subjects, "
            "lighting, mood, and composition (1-3 sentences).\n"
            "Keywords: 10-20 relevant keywords for search and cataloguing, "
            "covering subject matter, location type, mood, colours, "
            "photographic style, and season where apparent."
        )
        prompt_layout.addWidget(self.prompt_edit)

        preset_row = QHBoxLayout()
        preset_label = QLabel("Presets:")
        preset_label.setStyleSheet("color: #888; font-size: 11px;")
        preset_row.addWidget(preset_label)

        for name, prompt_text in [
            ("Landscape", (
                "Analyse this landscape photograph.\n\n"
                "Title: A concise, evocative title (5-10 words).\n"
                "Caption: Describe the scene, terrain, weather, light quality, "
                "and mood (1-3 sentences).\n"
                "Keywords: 15-20 keywords covering landscape type, geological "
                "features, vegetation, sky conditions, season, time of day, "
                "colours, and photographic style."
            )),
            ("Event", (
                "Analyse this event photograph.\n\n"
                "Title: A descriptive title capturing the moment (5-10 words).\n"
                "Caption: Describe the action, participants, setting, and "
                "atmosphere (1-3 sentences).\n"
                "Keywords: 15-20 keywords covering the event type, activities, "
                "people, setting, mood, and photographic style."
            )),
            ("Product", (
                "Analyse this product photograph.\n\n"
                "Title: A clear, descriptive title (5-10 words).\n"
                "Caption: Describe the product, its features, styling, "
                "and presentation (1-3 sentences).\n"
                "Keywords: 15-20 keywords covering product type, features, "
                "materials, colours, style, and use case."
            )),
            ("Default", None),
        ]:
            btn = QPushButton(name)
            btn.setFixedHeight(24)
            btn.setStyleSheet("font-size: 11px; padding: 2px 10px;")
            if prompt_text:
                btn.clicked.connect(lambda _, t=prompt_text: self.prompt_edit.setText(t))
            else:
                btn.clicked.connect(self._reset_prompt)
            preset_row.addWidget(btn)

        preset_row.addStretch()
        prompt_layout.addLayout(preset_row)
        settings_layout.addWidget(prompt_group)

        # Batch context
        context_group = QGroupBox("Batch Context (applied to all photos)")
        context_layout = QGridLayout(context_group)
        context_layout.setSpacing(10)
        context_layout.setContentsMargins(12, 8, 12, 12)

        fields = [
            ("Location:", "ctx_location", "e.g. Berry, NSW, Australia"),
            ("Event:", "ctx_event", "e.g. Berry Show 2026"),
            ("Date/Time:", "ctx_datetime", "e.g. Morning, March 2026"),
            ("Photographer:", "ctx_photographer", "e.g. Andy Hutchinson"),
            ("Notes:", "ctx_notes", "Any additional context for the AI"),
        ]
        self.context_fields = {}
        for row, (label, key, placeholder) in enumerate(fields):
            lbl = QLabel(label)
            lbl.setStyleSheet("color: #a0a0a0; font-size: 12px;")
            context_layout.addWidget(lbl, row, 0)
            edit = QLineEdit()
            edit.setPlaceholderText(placeholder)
            context_layout.addWidget(edit, row, 1)
            self.context_fields[key] = edit
        settings_layout.addWidget(context_group)

        # Options
        options_group = QGroupBox("Options")
        options_layout = QVBoxLayout(options_group)

        self.backup_check = QCheckBox("Create backup files when writing metadata")
        self.backup_check.setChecked(True)
        options_layout.addWidget(self.backup_check)

        self.overwrite_check = QCheckBox("Overwrite existing IPTC metadata")
        self.overwrite_check.setChecked(True)
        options_layout.addWidget(self.overwrite_check)

        settings_layout.addWidget(options_group)
        settings_layout.addStretch()

        tabs.addTab(settings_tab, "Settings")

        # ── Keywords Tab ──
        keywords_tab = QWidget()
        kw_layout = QVBoxLayout(keywords_tab)

        kw_desc = QLabel(
            "Optional: supply a keyword vocabulary. The model will prefer "
            "these terms where applicable, giving you consistent keywording."
        )
        kw_desc.setWordWrap(True)
        kw_desc.setStyleSheet("color: #888; font-size: 12px; margin-bottom: 8px;")
        kw_layout.addWidget(kw_desc)

        self.keywords_edit = QPlainTextEdit()
        self.keywords_edit.setPlaceholderText(
            "One keyword per line, or comma-separated.\n\n"
            "landscape, seascape, golden hour, blue hour,\n"
            "sunrise, sunset, cloudy, stormy, misty..."
        )
        kw_layout.addWidget(self.keywords_edit)

        kw_btn_row = QHBoxLayout()
        load_kw_btn = QPushButton("Load from File")
        load_kw_btn.clicked.connect(self._load_keywords)
        kw_btn_row.addWidget(load_kw_btn)
        clear_kw_btn = QPushButton("Clear")
        clear_kw_btn.clicked.connect(self.keywords_edit.clear)
        kw_btn_row.addWidget(clear_kw_btn)
        kw_btn_row.addStretch()
        kw_layout.addLayout(kw_btn_row)

        tabs.addTab(keywords_tab, "Keywords")

        # ── Results Tab ──
        results_tab = QWidget()
        results_layout = QVBoxLayout(results_tab)
        results_layout.setContentsMargins(0, 0, 0, 0)
        results_layout.setSpacing(0)

        results_splitter = QSplitter(Qt.Horizontal)
        results_splitter.setHandleWidth(3)

        # Left: file list
        results_list_widget = QWidget()
        results_list_layout = QVBoxLayout(results_list_widget)
        results_list_layout.setContentsMargins(0, 0, 0, 0)
        results_list_layout.setSpacing(4)

        self.results_table = QTableWidget()
        self.results_table.setColumnCount(2)
        self.results_table.setHorizontalHeaderLabels(["", "Filename"])
        self.results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.results_table.setColumnWidth(0, 16)
        self.results_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.results_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.results_table.setShowGrid(False)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setStyleSheet(
            self.results_table.styleSheet() +
            "QTableWidget { alternate-background-color: #1c1c20; }"
        )
        self.results_table.currentCellChanged.connect(self._on_result_selected)
        results_list_layout.addWidget(self.results_table)

        results_nav_row = QHBoxLayout()
        self.results_prev_btn = QPushButton("◀ Prev")
        self.results_prev_btn.setFixedHeight(28)
        self.results_prev_btn.setStyleSheet("font-size: 11px; padding: 2px 10px;")
        self.results_prev_btn.clicked.connect(self._results_prev)
        results_nav_row.addWidget(self.results_prev_btn)

        self.results_pos_label = QLabel("0 / 0")
        self.results_pos_label.setAlignment(Qt.AlignCenter)
        self.results_pos_label.setStyleSheet("color: #888; font-size: 11px;")
        results_nav_row.addWidget(self.results_pos_label)

        self.results_next_btn = QPushButton("Next ▶")
        self.results_next_btn.setFixedHeight(28)
        self.results_next_btn.setStyleSheet("font-size: 11px; padding: 2px 10px;")
        self.results_next_btn.clicked.connect(self._results_next)
        results_nav_row.addWidget(self.results_next_btn)
        results_list_layout.addLayout(results_nav_row)

        results_splitter.addWidget(results_list_widget)

        # Right: detail/edit panel
        detail_widget = QWidget()
        detail_layout = QVBoxLayout(detail_widget)
        detail_layout.setContentsMargins(8, 0, 0, 0)
        detail_layout.setSpacing(8)

        # Filename header
        self.detail_filename = QLabel("Select a photo to view metadata")
        self.detail_filename.setStyleSheet(
            "font-size: 14px; font-weight: 600; color: #e8a23a; "
            "padding: 4px 0; border: none;"
        )
        detail_layout.addWidget(self.detail_filename)

        # Title
        title_label = QLabel("TITLE")
        title_label.setStyleSheet(
            "color: #888; font-size: 10px; font-weight: 600; "
            "letter-spacing: 1px; margin-top: 4px; border: none;"
        )
        detail_layout.addWidget(title_label)
        self.detail_title = QLineEdit()
        self.detail_title.setPlaceholderText("Title")
        self.detail_title.textChanged.connect(self._on_detail_edited)
        detail_layout.addWidget(self.detail_title)

        # Caption
        caption_label = QLabel("CAPTION")
        caption_label.setStyleSheet(
            "color: #888; font-size: 10px; font-weight: 600; "
            "letter-spacing: 1px; margin-top: 4px; border: none;"
        )
        detail_layout.addWidget(caption_label)
        self.detail_caption = QTextEdit()
        self.detail_caption.setPlaceholderText("Caption / description")
        self.detail_caption.setMinimumHeight(80)
        self.detail_caption.setMaximumHeight(140)
        self.detail_caption.textChanged.connect(self._on_detail_edited)
        detail_layout.addWidget(self.detail_caption)

        # Keywords
        kw_label = QLabel("KEYWORDS")
        kw_label.setStyleSheet(
            "color: #888; font-size: 10px; font-weight: 600; "
            "letter-spacing: 1px; margin-top: 4px; border: none;"
        )
        detail_layout.addWidget(kw_label)
        self.detail_keywords = QTextEdit()
        self.detail_keywords.setPlaceholderText(
            "Comma-separated keywords"
        )
        self.detail_keywords.setMinimumHeight(60)
        self.detail_keywords.setMaximumHeight(120)
        self.detail_keywords.textChanged.connect(self._on_detail_edited)
        detail_layout.addWidget(self.detail_keywords)

        # Keyword count
        self.kw_count_label = QLabel("")
        self.kw_count_label.setStyleSheet("color: #555; font-size: 11px; border: none;")
        detail_layout.addWidget(self.kw_count_label)

        detail_layout.addStretch()

        results_splitter.addWidget(detail_widget)
        results_splitter.setSizes([250, 500])

        results_layout.addWidget(results_splitter)
        tabs.addTab(results_tab, "Results")

        # Track which result is selected
        self._current_result_index = -1
        self._updating_detail = False

        # ── Log Tab ──
        log_tab = QWidget()
        log_layout = QVBoxLayout(log_tab)
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet(
            "font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace; "
            "font-size: 11px; color: #888;"
        )
        log_layout.addWidget(self.log_text)
        tabs.addTab(log_tab, "Log")

        right_layout.addWidget(tabs, 1)

        # ── Action buttons ──
        action_row = QHBoxLayout()

        self.generate_btn = QPushButton("▶  Generate Metadata")
        self.generate_btn.setObjectName("primaryBtn")
        self.generate_btn.setMinimumHeight(40)
        self.generate_btn.clicked.connect(self._start_processing)
        action_row.addWidget(self.generate_btn)

        self.stop_btn = QPushButton("■  Stop")
        self.stop_btn.setObjectName("dangerBtn")
        self.stop_btn.setMinimumHeight(40)
        self.stop_btn.setVisible(False)
        self.stop_btn.clicked.connect(self._stop_processing)
        action_row.addWidget(self.stop_btn)

        self.write_btn = QPushButton("💾  Write Metadata to Files")
        self.write_btn.setObjectName("writeBtn")
        self.write_btn.setMinimumHeight(40)
        self.write_btn.setEnabled(False)
        self.write_btn.clicked.connect(self._write_metadata)
        action_row.addWidget(self.write_btn)

        self.export_btn = QPushButton("📋  Export CSV")
        self.export_btn.setObjectName("exportBtn")
        self.export_btn.setMinimumHeight(40)
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._export_csv)
        action_row.addWidget(self.export_btn)

        right_layout.addLayout(action_row)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(False)
        right_layout.addWidget(self.progress_bar)

        # Status bar
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("statusLabel")
        right_layout.addWidget(self.status_label)

        splitter.addWidget(right_panel)
        splitter.setSizes([400, 700])

        main_layout.addWidget(splitter, 1)

        # ── Footer with logo ──
        logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.png")
        if os.path.exists(logo_path):
            footer = QHBoxLayout()
            footer.setContentsMargins(0, 4, 0, 0)
            logo_label = QLabel()
            logo_pixmap = QPixmap(logo_path)
            logo_pixmap = logo_pixmap.scaledToHeight(32, Qt.SmoothTransformation)
            logo_label.setPixmap(logo_pixmap)
            logo_label.setStyleSheet("border: none; opacity: 0.6;")
            footer.addWidget(logo_label)
            footer.addStretch()
            main_layout.addLayout(footer)

        # Kick off model check
        QTimer.singleShot(500, self._refresh_models)

    # ── Settings persistence ──

    def _load_settings(self):
        url = self.settings.value("ollama_url", "http://localhost:11434")
        self.ollama_url.setText(url)
        prompt = self.settings.value("prompt", "")
        if prompt:
            self.prompt_edit.setText(prompt)
        photographer = self.settings.value("photographer", "")
        if photographer:
            self.context_fields["ctx_photographer"].setText(photographer)
        backup = self.settings.value("create_backup", "true")
        self.backup_check.setChecked(backup == "true")

    def _save_settings(self):
        self.settings.setValue("ollama_url", self.ollama_url.text())
        self.settings.setValue("prompt", self.prompt_edit.toPlainText())
        self.settings.setValue(
            "create_backup",
            "true" if self.backup_check.isChecked() else "false"
        )
        self.settings.setValue(
            "photographer",
            self.context_fields["ctx_photographer"].text()
        )

    def closeEvent(self, event):
        self._save_settings()
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(3000)
        event.accept()

    # ── Logging ──

    def log(self, msg):
        self.log_text.appendPlainText(msg)

    # ── Model management ──

    def _refresh_models(self):
        url = self.ollama_url.text().rstrip("/")
        try:
            resp = requests.get(f"{url}/api/tags", timeout=5)
            resp.raise_for_status()
            models = resp.json().get("models", [])
            self.model_combo.clear()

            # Sort: prefer gemma3 models first
            model_names = sorted(
                [m["name"] for m in models],
                key=lambda n: (0 if "gemma3" in n.lower() else 1, n)
            )
            self.model_combo.addItems(model_names)

            # Default to gemma3:12b if available
            for i, name in enumerate(model_names):
                if "gemma3:12b" in name:
                    self.model_combo.setCurrentIndex(i)
                    break

            self.ollama_status.setText(f"● Ollama connected ({len(models)} models)")
            self.ollama_status.setStyleSheet("color: #27ae60; font-size: 12px;")
            self.log(f"Connected to Ollama at {url} ({len(models)} models)")

        except Exception as e:
            self.ollama_status.setText("● Ollama not connected")
            self.ollama_status.setStyleSheet("color: #c0392b; font-size: 12px;")
            self.log(f"Cannot connect to Ollama: {e}")
            self.model_combo.clear()

    # ── File handling ──

    def _browse_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Photos", "",
            "Images (*.jpg *.jpeg *.tif *.tiff *.png *.dng *.webp "
            "*.cr2 *.cr3 *.nef *.arw *.orf *.raf *.rw2 *.pef *.srw *.raw)"
        )
        if files:
            self._on_files_dropped(files)

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder:
            files = []
            for root, dirs, fnames in os.walk(folder):
                for f in fnames:
                    fp = os.path.join(root, f)
                    if Path(fp).suffix.lower() in SUPPORTED_EXTENSIONS:
                        files.append(fp)
            if files:
                self._on_files_dropped(files)

    def _on_files_dropped(self, filepaths):
        existing = {p.filepath for p in self.photos}
        new_files = [f for f in filepaths if f not in existing]

        for fp in new_files:
            photo = PhotoItem(
                filepath=fp,
                filename=os.path.basename(fp),
            )
            # Generate thumbnail
            try:
                ext = Path(fp).suffix.lower()
                if ext in RAW_EXTENSIONS and HAS_RAWPY:
                    with rawpy.imread(fp) as raw:
                        rgb = raw.postprocess(
                            use_camera_wb=True,
                            half_size=True,
                        )
                    img = Image.fromarray(rgb)
                else:
                    img = Image.open(fp)
                img.thumbnail((48, 48), Image.LANCZOS)
                if img.mode != "RGB":
                    img = img.convert("RGB")
                data = img.tobytes("raw", "RGB")
                qimg = QImage(data, img.width, img.height, img.width * 3, QImage.Format_RGB888)
                photo.thumbnail = QPixmap.fromImage(qimg)
            except Exception:
                pass

            self.photos.append(photo)

        self._refresh_photo_table()
        self.log(f"Added {len(new_files)} photos ({len(self.photos)} total)")

    def _clear_all(self):
        self.photos.clear()
        self._current_result_index = -1
        self._refresh_photo_table()
        self._refresh_results_table()
        # Clear detail panel
        self._updating_detail = True
        self.detail_filename.setText("Select a photo to view metadata")
        self.detail_title.clear()
        self.detail_caption.clear()
        self.detail_keywords.clear()
        self.kw_count_label.setText("")
        self._updating_detail = False
        self.log("Cleared all photos")

    def _refresh_photo_table(self):
        self.photo_table.setRowCount(len(self.photos))
        for row, photo in enumerate(self.photos):
            # Status dot
            dot = StatusDot(photo.status)
            container = QWidget()
            cl = QHBoxLayout(container)
            cl.setContentsMargins(4, 0, 0, 0)
            cl.addWidget(dot)
            self.photo_table.setCellWidget(row, 0, container)

            # Filename
            item = QTableWidgetItem(photo.filename)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            if photo.status == "error":
                item.setForeground(QColor("#c0392b"))
            self.photo_table.setItem(row, 1, item)

            # Status text
            status_item = QTableWidgetItem(photo.status.capitalize())
            status_item.setFlags(status_item.flags() & ~Qt.ItemIsEditable)
            status_colours = {
                "pending": "#555",
                "processing": "#e8a23a",
                "done": "#27ae60",
                "error": "#c0392b",
            }
            status_item.setForeground(QColor(status_colours.get(photo.status, "#555")))
            self.photo_table.setItem(row, 2, status_item)

            # Title preview
            title_text = photo.metadata.title if photo.metadata else ""
            title_item = QTableWidgetItem(title_text)
            title_item.setFlags(title_item.flags() & ~Qt.ItemIsEditable)
            self.photo_table.setItem(row, 3, title_item)

            self.photo_table.setRowHeight(row, 32)

        total = len(self.photos)
        done = sum(1 for p in self.photos if p.status == "done")
        self.photo_count_label.setText(f"{total} photos loaded, {done} processed")

    def _on_photo_selected(self, row, col, prev_row, prev_col):
        pass  # Could show preview in future

    # ── Processing ──

    def _get_context_string(self):
        parts = []
        field_map = {
            "ctx_location": "Location",
            "ctx_event": "Event",
            "ctx_datetime": "Date/Time",
            "ctx_photographer": "Photographer",
            "ctx_notes": "Additional context",
        }
        for key, label in field_map.items():
            val = self.context_fields[key].text().strip()
            if val:
                parts.append(f"{label}: {val}")
        return "; ".join(parts)

    def _get_keywords_list(self):
        text = self.keywords_edit.toPlainText().strip()
        if not text:
            return []
        # Handle both comma-separated and newline-separated
        keywords = []
        for line in text.split("\n"):
            for kw in line.split(","):
                kw = kw.strip()
                if kw:
                    keywords.append(kw)
        return list(dict.fromkeys(keywords))  # Deduplicate, preserve order

    def _start_processing(self):
        if not self.photos:
            self.status_label.setText("No photos loaded")
            return
        if not self.model_combo.currentText():
            self.status_label.setText("No model selected. Is Ollama running?")
            return

        pending = [p for p in self.photos if p.status != "done"]
        if not pending:
            self.status_label.setText("All photos already processed")
            return

        self.generate_btn.setVisible(False)
        self.stop_btn.setVisible(True)
        self.write_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(len(self.photos))
        self.progress_bar.setValue(0)

        self.worker = OllamaWorker(
            photos=self.photos,
            model=self.model_combo.currentText(),
            prompt=self.prompt_edit.toPlainText(),
            context=self._get_context_string(),
            ollama_url=self.ollama_url.text().rstrip("/"),
            keywords_list=self._get_keywords_list(),
        )
        self.worker.progress.connect(self._on_progress)
        self.worker.result.connect(self._on_result)
        self.worker.finished_all.connect(self._on_finished)
        self.worker.log_message.connect(self.log)
        self.worker.start()

        self.status_label.setText("Processing...")

    def _stop_processing(self):
        if self.worker:
            self.worker.cancel()
            self.log("Stopping...")
            self.status_label.setText("Stopping...")

    def _on_progress(self, index, status):
        self.photos[index].status = status
        self._refresh_photo_table()
        self.progress_bar.setValue(
            sum(1 for p in self.photos if p.status in ("done", "error"))
        )

    def _on_result(self, index, result):
        if isinstance(result, PhotoMetadata):
            self.photos[index].metadata = result
            self.photos[index].status = "done"
        else:
            self.photos[index].status = "error"
            self.photos[index].error_msg = str(result)

        self._refresh_photo_table()
        self.progress_bar.setValue(
            sum(1 for p in self.photos if p.status in ("done", "error"))
        )

    def _on_finished(self):
        self.generate_btn.setVisible(True)
        self.stop_btn.setVisible(False)
        self.progress_bar.setVisible(False)

        done = sum(1 for p in self.photos if p.status == "done")
        errors = sum(1 for p in self.photos if p.status == "error")
        self.status_label.setText(f"Finished: {done} processed, {errors} errors")

        if done > 0:
            self.write_btn.setEnabled(True)
            self.export_btn.setEnabled(True)
            self._refresh_results_table()

        self.worker = None

    # ── Results ──

    def _refresh_results_table(self):
        completed = [p for p in self.photos if p.status == "done" and p.metadata]
        self.results_table.setRowCount(len(completed))

        for row, photo in enumerate(completed):
            # Status dot (green = done)
            dot = StatusDot("done")
            container = QWidget()
            cl = QHBoxLayout(container)
            cl.setContentsMargins(4, 0, 0, 0)
            cl.addWidget(dot)
            self.results_table.setCellWidget(row, 0, container)

            # Filename
            item = QTableWidgetItem(photo.filename)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.results_table.setItem(row, 1, item)
            self.results_table.setRowHeight(row, 30)

        # Auto-select first if nothing selected
        if completed and self._current_result_index < 0:
            self.results_table.selectRow(0)

        self._update_results_pos_label()

    def _get_completed_photos(self):
        return [p for p in self.photos if p.status == "done" and p.metadata]

    def _on_result_selected(self, row, col, prev_row, prev_col):
        completed = self._get_completed_photos()
        if row < 0 or row >= len(completed):
            return
        self._current_result_index = row
        self._load_detail(completed[row])
        self._update_results_pos_label()

    def _load_detail(self, photo):
        """Load a photo's metadata into the detail panel."""
        self._updating_detail = True
        self.detail_filename.setText(photo.filename)
        self.detail_title.setText(photo.metadata.title)
        self.detail_caption.setText(photo.metadata.caption)
        self.detail_keywords.setText(", ".join(photo.metadata.keywords))
        kw_count = len(photo.metadata.keywords)
        self.kw_count_label.setText(f"{kw_count} keyword{'s' if kw_count != 1 else ''}")
        self._updating_detail = False

    def _on_detail_edited(self):
        """Sync edits from detail panel back to the photo data."""
        if self._updating_detail:
            return
        completed = self._get_completed_photos()
        if self._current_result_index < 0 or self._current_result_index >= len(completed):
            return
        photo = completed[self._current_result_index]
        photo.metadata.title = self.detail_title.text()
        photo.metadata.caption = self.detail_caption.toPlainText()
        kws_text = self.detail_keywords.toPlainText()
        photo.metadata.keywords = [k.strip() for k in kws_text.split(",") if k.strip()]
        kw_count = len(photo.metadata.keywords)
        self.kw_count_label.setText(f"{kw_count} keyword{'s' if kw_count != 1 else ''}")

    def _results_prev(self):
        completed = self._get_completed_photos()
        if not completed:
            return
        new_idx = max(0, self._current_result_index - 1)
        self.results_table.selectRow(new_idx)

    def _results_next(self):
        completed = self._get_completed_photos()
        if not completed:
            return
        new_idx = min(len(completed) - 1, self._current_result_index + 1)
        self.results_table.selectRow(new_idx)

    def _update_results_pos_label(self):
        completed = self._get_completed_photos()
        total = len(completed)
        pos = self._current_result_index + 1 if self._current_result_index >= 0 else 0
        self.results_pos_label.setText(f"{pos} / {total}")

    # ── Write metadata ──

    def _write_metadata(self):
        if not MetadataWriter.check_exiftool():
            QMessageBox.critical(
                self, "Error",
                "exiftool is not installed.\n\n"
                "macOS: brew install exiftool\n"
                "Linux: sudo apt install libimage-exiftool-perl\n"
                "Windows: https://exiftool.org"
            )
            return

        completed = [p for p in self.photos if p.status == "done" and p.metadata]
        if not completed:
            return

        reply = QMessageBox.question(
            self, "Write Metadata",
            f"Write metadata to {len(completed)} file(s)?\n\n"
            f"{'Backup files will be created.' if self.backup_check.isChecked() else 'WARNING: No backup will be created!'}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply != QMessageBox.Yes:
            return

        success = 0
        errors = 0
        for photo in completed:
            try:
                MetadataWriter.write_metadata(
                    photo.filepath,
                    photo.metadata,
                    backup=self.backup_check.isChecked()
                )
                success += 1
                self.log(f"Wrote metadata: {photo.filename}")
            except Exception as e:
                errors += 1
                self.log(f"Error writing {photo.filename}: {e}")

        self.status_label.setText(f"Written: {success} OK, {errors} errors")
        QMessageBox.information(
            self, "Complete",
            f"Metadata written to {success} file(s).\n"
            f"Errors: {errors}"
        )

    # ── Export ──

    def _export_csv(self):
        completed = [p for p in self.photos if p.status == "done" and p.metadata]
        if not completed:
            QMessageBox.information(self, "Export", "No processed photos to export.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", "photo_metadata.csv", "CSV Files (*.csv)"
        )
        if not path:
            return

        import csv
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Filename", "Filepath", "Title", "Caption", "Keywords"])
            for photo in completed:
                writer.writerow([
                    photo.filename,
                    photo.filepath,
                    photo.metadata.title,
                    photo.metadata.caption,
                    "; ".join(photo.metadata.keywords),
                ])
        self.log(f"Exported CSV: {path}")
        self.status_label.setText(f"CSV exported to {path}")

    # ── Keywords loading ──

    def _load_keywords(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Keywords", "",
            "Text Files (*.txt *.csv);;All Files (*)"
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            self.keywords_edit.setPlainText(text)
            self.log(f"Loaded keywords from {path}")
        except Exception as e:
            self.log(f"Error loading keywords: {e}")

    # ── Prompt reset ──

    def _reset_prompt(self):
        self.prompt_edit.setText(
            "Analyse this photograph and generate metadata for it.\n\n"
            "Title: A concise, descriptive title (5-10 words).\n"
            "Caption: A detailed description of the scene, subjects, "
            "lighting, mood, and composition (1-3 sentences).\n"
            "Keywords: 10-20 relevant keywords for search and cataloguing, "
            "covering subject matter, location type, mood, colours, "
            "photographic style, and season where apparent."
        )


# ─────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)

    # Dark palette
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#1a1a1e"))
    palette.setColor(QPalette.WindowText, QColor("#e0e0e0"))
    palette.setColor(QPalette.Base, QColor("#222226"))
    palette.setColor(QPalette.AlternateBase, QColor("#1c1c20"))
    palette.setColor(QPalette.Text, QColor("#e0e0e0"))
    palette.setColor(QPalette.Button, QColor("#2a2a30"))
    palette.setColor(QPalette.ButtonText, QColor("#e0e0e0"))
    palette.setColor(QPalette.Highlight, QColor("#e8a23a"))
    palette.setColor(QPalette.HighlightedText, QColor("#1a1a1e"))
    app.setPalette(palette)

    window = PhotoScribe()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
