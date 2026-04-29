"""Unit tests for `OllamaWorker._build_prompt` and `_encode_image`.

These exercise pure helpers on a `QThread` subclass without starting a
thread or running an event loop. We instantiate the worker, call the
methods directly, and assert on return values. No Ollama, no
QApplication, no real RAW files.
"""
from __future__ import annotations

import base64
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

import photoscribe
from photoscribe import OllamaWorker


def _make_worker(*, prompt: str = "describe this", context: str = "",
                 keywords_list: list[str] | None = None) -> OllamaWorker:
    """Build a worker with the minimum stubs the constructor needs.
    Tests that exercise pure helpers don't care about model/url."""
    return OllamaWorker(
        photos=[],
        model="test-model",
        prompt=prompt,
        context=context,
        ollama_url="http://localhost:11434",
        keywords_list=keywords_list,
    )


# ─────────────────────────────────────────────────────────
# _build_prompt
# ─────────────────────────────────────────────────────────

def test_build_prompt_includes_context_when_set():
    worker = _make_worker(context="Shot during a thunderstorm in Iceland.")
    prompt = worker._build_prompt()
    assert "Shot during a thunderstorm in Iceland." in prompt
    assert prompt.startswith("Context for this photo:")


def test_build_prompt_omits_context_when_empty():
    worker = _make_worker(context="")
    prompt = worker._build_prompt()
    assert "Context for this photo:" not in prompt


def test_build_prompt_omits_context_when_whitespace_only():
    worker = _make_worker(context="   \n  ")
    prompt = worker._build_prompt()
    assert "Context for this photo:" not in prompt


def test_build_prompt_includes_keyword_vocab_when_provided():
    worker = _make_worker(keywords_list=["mountain", "snow", "alpine"])
    prompt = worker._build_prompt()
    assert "vocabulary" in prompt
    assert "mountain, snow, alpine" in prompt


def test_build_prompt_caps_vocab_at_200_keywords():
    """The vocabulary slice is `[:200]` — keyword #201 must be absent."""
    keywords = [f"kw{i:03d}" for i in range(250)]
    worker = _make_worker(keywords_list=keywords)
    prompt = worker._build_prompt()
    assert "kw199" in prompt   # 200th keyword (0-indexed)
    assert "kw200" not in prompt
    assert "kw249" not in prompt


def test_build_prompt_omits_vocab_section_when_keywords_empty():
    worker = _make_worker(keywords_list=[])
    prompt = worker._build_prompt()
    assert "vocabulary" not in prompt


def test_build_prompt_always_includes_json_format_instruction():
    """The trailing JSON-format instruction is load-bearing — the response
    parser depends on the model returning a single JSON object. CLAUDE.md
    explicitly calls this out as not-to-be-removed."""
    worker = _make_worker()
    prompt = worker._build_prompt()
    assert "Respond ONLY with valid JSON" in prompt
    assert '"title"' in prompt
    assert '"caption"' in prompt
    assert '"keywords"' in prompt


# ─────────────────────────────────────────────────────────
# _encode_image
# ─────────────────────────────────────────────────────────

def _decode_b64_to_image(b64: str) -> Image.Image:
    return Image.open(BytesIO(base64.b64decode(b64)))


def test_encode_image_jpeg_returns_base64_string(tmp_jpeg):
    worker = _make_worker()
    encoded = worker._encode_image(str(tmp_jpeg))
    assert isinstance(encoded, str)
    # Round-trip — the result must decode back to a JPEG.
    img = _decode_b64_to_image(encoded)
    assert img.format == "JPEG"


def test_encode_image_preserves_small_image_size(tmp_jpeg):
    """200x200 is below the 1024 cap; the worker should not upscale."""
    worker = _make_worker()
    img = _decode_b64_to_image(worker._encode_image(str(tmp_jpeg)))
    assert img.size == (200, 200)


def test_encode_image_resizes_oversized(tmp_jpeg_large):
    """2000x2000 exceeds the 1024 cap; longest side should land at 1024."""
    worker = _make_worker()
    img = _decode_b64_to_image(worker._encode_image(str(tmp_jpeg_large)))
    assert max(img.size) == 1024


def test_encode_image_dispatches_to_rawpy_for_raw_extension(tmp_path):
    """A `.cr2` filepath must go through `rawpy.imread`, not `Image.open`.

    We don't bundle a real RAW fixture (per the contribution plan) — we
    mock `rawpy.imread` and assert the dispatch chose the right branch.
    """
    raw_path = tmp_path / "shot.cr2"
    raw_path.write_bytes(b"not a real raw, won't be parsed")

    # Build a fake rawpy context manager that yields a postprocess() result.
    fake_rgb_array = _fake_rgb_array(width=300, height=200)
    fake_raw = MagicMock()
    fake_raw.__enter__.return_value = fake_raw
    fake_raw.__exit__.return_value = False
    fake_raw.postprocess.return_value = fake_rgb_array

    worker = _make_worker()
    with patch("photoscribe.rawpy.imread", return_value=fake_raw) as imread, \
         patch("photoscribe.Image.open") as image_open:
        encoded = worker._encode_image(str(raw_path))

    imread.assert_called_once_with(str(raw_path))
    image_open.assert_not_called()
    assert isinstance(encoded, str)
    assert len(encoded) > 0


def test_encode_image_passes_expected_postprocess_options(tmp_path):
    """Sanity-lock the rawpy.postprocess() options. CLAUDE.md documents
    `half_size=True, use_camera_wb=True` as deliberate (faster decode +
    plenty for AI analysis)."""
    raw_path = tmp_path / "shot.nef"
    raw_path.write_bytes(b"stub")

    fake_raw = MagicMock()
    fake_raw.__enter__.return_value = fake_raw
    fake_raw.__exit__.return_value = False
    fake_raw.postprocess.return_value = _fake_rgb_array()

    worker = _make_worker()
    with patch("photoscribe.rawpy.imread", return_value=fake_raw):
        worker._encode_image(str(raw_path))

    fake_raw.postprocess.assert_called_once()
    kwargs = fake_raw.postprocess.call_args.kwargs
    assert kwargs.get("half_size") is True
    assert kwargs.get("use_camera_wb") is True


def test_encode_image_raises_when_rawpy_missing_for_raw(tmp_path, monkeypatch):
    """If `rawpy` failed to import at module load, attempting a RAW file
    must raise — not crash deeper, not silently skip."""
    raw_path = tmp_path / "shot.cr2"
    raw_path.write_bytes(b"stub")

    monkeypatch.setattr(photoscribe, "HAS_RAWPY", False)

    worker = _make_worker()
    with pytest.raises(RuntimeError, match="rawpy not installed"):
        worker._encode_image(str(raw_path))


def test_encode_image_raises_runtime_error_on_decode_failure(tmp_path):
    """Pillow can't decode a file that isn't really an image. The worker
    wraps the failure as RuntimeError so callers see a uniform error type."""
    fake_jpeg = tmp_path / "broken.jpg"
    fake_jpeg.write_bytes(b"this is not a jpeg")

    worker = _make_worker()
    with pytest.raises(RuntimeError, match="Failed to load image"):
        worker._encode_image(str(fake_jpeg))


def _fake_rgb_array(width: int = 300, height: int = 200):
    """Build a numpy-like RGB ndarray. We use Pillow itself to make a real
    array via tobytes() and then numpy.frombuffer — but rawpy depends on
    numpy directly, and numpy is a transitive dep of rawpy. Importing it
    here is safe whenever rawpy is available."""
    import numpy as np
    return np.full((height, width, 3), fill_value=128, dtype=np.uint8)
