"""Shared fixtures for the PhotoScribe test suite.

These fixtures keep individual test files focused on assertions. The suite
is designed to run on a clean checkout: no Ollama server, no exiftool, no
RAW files. All external interactions are mocked at boundaries
(`subprocess.run`, `requests.post`, `rawpy.imread`).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image

# Make the project root importable so tests can `import photoscribe`.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def tmp_jpeg(tmp_path: Path) -> Path:
    """A small valid JPEG. Sufficient for _encode_image happy-path tests
    where pixel content does not matter."""
    path = tmp_path / "fixture.jpg"
    Image.new("RGB", (200, 200), color=(220, 90, 60)).save(path, "JPEG")
    return path


@pytest.fixture
def tmp_jpeg_large(tmp_path: Path) -> Path:
    """A 2000x2000 JPEG. Used to exercise the >1024px resize branch."""
    path = tmp_path / "fixture-large.jpg"
    Image.new("RGB", (2000, 2000), color=(40, 80, 200)).save(path, "JPEG")
    return path


def make_completed_process(
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> MagicMock:
    """Build a `subprocess.CompletedProcess`-shaped mock.

    A bare MagicMock with these three attributes set is enough — the
    callers in `MetadataWriter` only read `returncode`, `stdout`, and
    `stderr`. Returning a MagicMock (rather than a real
    CompletedProcess) keeps the import surface minimal.
    """
    mock = MagicMock()
    mock.returncode = returncode
    mock.stdout = stdout
    mock.stderr = stderr
    return mock


def make_ollama_response(content: str, status_code: int = 200) -> MagicMock:
    """Build a `requests.Response`-shaped mock with the given message
    content. Mirrors the shape that `OllamaWorker.run` reads:
    `resp.json()["message"]["content"]` plus `resp.raise_for_status()`.
    """
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = {"message": {"content": content}}
    if status_code >= 400:
        mock.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    else:
        mock.raise_for_status.return_value = None
    return mock
