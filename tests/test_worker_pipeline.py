"""Integration tests for `OllamaWorker.run()`.

We mock `requests.post` and feed canned response payloads, then call
`worker.run()` synchronously (not `start()`) so signal emissions land via
direct connections without an event loop. A real fixture JPEG is fed
through `_encode_image` so the encode path is exercised end-to-end.

These cover the LLM-response parser inline at lines 212-225 of
photoscribe.py: markdown-fence stripping, JSON slicing from prose, and
JSONDecodeError handling.
"""
from __future__ import annotations

import json
from unittest.mock import patch

from photoscribe import OllamaWorker, PhotoItem, PhotoMetadata
from tests.conftest import make_ollama_response


def _build_worker(photos):
    return OllamaWorker(
        photos=photos,
        model="test-model",
        prompt="describe this",
        context="",
        ollama_url="http://localhost:11434",
    )


def _capture_results(worker):
    """Wire a list to the `result` signal. Direct connection on the same
    thread → emissions invoke the slot synchronously, no QApplication."""
    captured: list[tuple[int, object]] = []
    worker.result.connect(lambda i, payload: captured.append((i, payload)))
    return captured


def _photo_from(path) -> PhotoItem:
    return PhotoItem(filepath=str(path), filename=path.name)


# ─────────────────────────────────────────────────────────
# Happy path & response-parser variants
# ─────────────────────────────────────────────────────────

def test_worker_happy_path_emits_metadata(tmp_jpeg):
    response_json = json.dumps({
        "title": "Red square",
        "caption": "A solid red square against a plain background.",
        "keywords": ["red", "square", "minimal"],
    })
    worker = _build_worker([_photo_from(tmp_jpeg)])
    captured = _capture_results(worker)

    with patch("photoscribe.requests.post",
               return_value=make_ollama_response(response_json)):
        worker.run()

    assert len(captured) == 1
    index, payload = captured[0]
    assert index == 0
    assert isinstance(payload, PhotoMetadata)
    assert payload.title == "Red square"
    assert payload.caption.startswith("A solid red square")
    assert payload.keywords == ["red", "square", "minimal"]


def test_worker_strips_markdown_json_fences(tmp_jpeg):
    """Models often wrap JSON in ```json fences. The parser must strip them."""
    fenced = (
        "```json\n"
        '{"title": "t", "caption": "c", "keywords": ["k1", "k2"]}\n'
        "```"
    )
    worker = _build_worker([_photo_from(tmp_jpeg)])
    captured = _capture_results(worker)

    with patch("photoscribe.requests.post",
               return_value=make_ollama_response(fenced)):
        worker.run()

    _, payload = captured[0]
    assert isinstance(payload, PhotoMetadata)
    assert payload.title == "t"
    assert payload.keywords == ["k1", "k2"]


def test_worker_strips_bare_triple_backtick_fences(tmp_jpeg):
    """Some models use plain ``` fences without a language hint."""
    fenced = '```\n{"title": "t", "caption": "c", "keywords": []}\n```'
    worker = _build_worker([_photo_from(tmp_jpeg)])
    captured = _capture_results(worker)

    with patch("photoscribe.requests.post",
               return_value=make_ollama_response(fenced)):
        worker.run()

    _, payload = captured[0]
    assert isinstance(payload, PhotoMetadata)
    assert payload.title == "t"


def test_worker_slices_json_from_surrounding_prose(tmp_jpeg):
    """If the model wraps the JSON in a sentence, the parser falls back to
    the first `{` … last `}` slice."""
    chatty = (
        'Sure! Here is your metadata: {"title": "sliced", "caption": "ok", '
        '"keywords": ["x"]}  hope that helps!'
    )
    worker = _build_worker([_photo_from(tmp_jpeg)])
    captured = _capture_results(worker)

    with patch("photoscribe.requests.post",
               return_value=make_ollama_response(chatty)):
        worker.run()

    _, payload = captured[0]
    assert isinstance(payload, PhotoMetadata)
    assert payload.title == "sliced"
    assert payload.keywords == ["x"]


def test_worker_emits_error_string_on_invalid_json(tmp_jpeg):
    """When the response can't be parsed at all, `result` carries an error
    string instead of a PhotoMetadata. The UI uses the type to branch."""
    worker = _build_worker([_photo_from(tmp_jpeg)])
    captured = _capture_results(worker)

    with patch("photoscribe.requests.post",
               return_value=make_ollama_response("definitely not json")):
        worker.run()

    _, payload = captured[0]
    assert isinstance(payload, str)
    assert "parse" in payload.lower() or "json" in payload.lower()


def test_worker_strips_whitespace_from_metadata_fields(tmp_jpeg):
    """The constructor for PhotoMetadata strips title/caption/keywords."""
    response_json = json.dumps({
        "title": "  spaced title  ",
        "caption": "  ",  # whitespace-only → becomes empty after strip
        "keywords": ["  word  ", "", "  "],  # blanks should be filtered
    })
    worker = _build_worker([_photo_from(tmp_jpeg)])
    captured = _capture_results(worker)

    with patch("photoscribe.requests.post",
               return_value=make_ollama_response(response_json)):
        worker.run()

    _, payload = captured[0]
    assert isinstance(payload, PhotoMetadata)
    assert payload.title == "spaced title"
    assert payload.caption == ""
    assert payload.keywords == ["word"]


# ─────────────────────────────────────────────────────────
# Batch behaviour
# ─────────────────────────────────────────────────────────

def test_worker_skips_photos_already_done(tmp_jpeg):
    """A pre-existing `status='done'` PhotoItem must not be reprocessed —
    `requests.post` is only called for the pending one."""
    done_photo = _photo_from(tmp_jpeg)
    done_photo.status = "done"
    pending_photo = _photo_from(tmp_jpeg)

    response_json = json.dumps({"title": "t", "caption": "c", "keywords": []})
    worker = _build_worker([done_photo, pending_photo])
    captured = _capture_results(worker)

    with patch("photoscribe.requests.post",
               return_value=make_ollama_response(response_json)) as post:
        worker.run()

    assert post.call_count == 1
    # Only the pending photo (index 1) emits a result.
    assert len(captured) == 1
    assert captured[0][0] == 1


def test_worker_processes_multiple_photos_in_order(tmp_jpeg):
    """Two pending photos → two emissions, indices 0 and 1, both
    PhotoMetadata."""
    photos = [_photo_from(tmp_jpeg), _photo_from(tmp_jpeg)]
    response_json = json.dumps({"title": "t", "caption": "c", "keywords": []})
    worker = _build_worker(photos)
    captured = _capture_results(worker)

    with patch("photoscribe.requests.post",
               return_value=make_ollama_response(response_json)) as post:
        worker.run()

    assert post.call_count == 2
    assert [c[0] for c in captured] == [0, 1]
    assert all(isinstance(c[1], PhotoMetadata) for c in captured)


def test_worker_cancel_stops_batch_mid_run(tmp_jpeg):
    """Setting `_cancelled` between photos halts the loop."""
    photos = [_photo_from(tmp_jpeg), _photo_from(tmp_jpeg), _photo_from(tmp_jpeg)]
    response_json = json.dumps({"title": "t", "caption": "c", "keywords": []})
    worker = _build_worker(photos)
    captured = _capture_results(worker)

    call_count = {"n": 0}

    def fake_post(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            worker.cancel()
        return make_ollama_response(response_json)

    with patch("photoscribe.requests.post", side_effect=fake_post):
        worker.run()

    # First photo processed, then cancel kicked in before photo #2.
    assert len(captured) == 1
    assert captured[0][0] == 0
