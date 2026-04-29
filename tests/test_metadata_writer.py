"""Unit tests for `photoscribe.MetadataWriter`.

The class shells out to `exiftool` via `subprocess.run`. These tests patch
`subprocess.run` and inspect the captured argv, so they run with no
exiftool installed and never touch the filesystem.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from photoscribe import MetadataWriter, PhotoMetadata
from tests.conftest import make_completed_process

# ─────────────────────────────────────────────────────────
# read_existing_metadata
# ─────────────────────────────────────────────────────────

def test_read_existing_metadata_parses_json():
    stdout = json.dumps([{
        "ObjectName": "A title",
        "Caption-Abstract": "A caption",
        "Keywords": ["sky", "tree"],
    }])
    with patch("photoscribe.subprocess.run",
               return_value=make_completed_process(stdout=stdout)):
        title, caption, keywords = MetadataWriter.read_existing_metadata("/x.jpg")
    assert title == "A title"
    assert caption == "A caption"
    assert keywords == ["sky", "tree"]


def test_read_existing_metadata_handles_string_keywords():
    """exiftool emits a single keyword as a bare string, not a list."""
    stdout = json.dumps([{
        "ObjectName": "t",
        "Caption-Abstract": "c",
        "Keywords": "lonely",
    }])
    with patch("photoscribe.subprocess.run",
               return_value=make_completed_process(stdout=stdout)):
        _, _, keywords = MetadataWriter.read_existing_metadata("/x.jpg")
    assert keywords == ["lonely"]


def test_read_existing_metadata_returns_empty_on_subprocess_failure():
    with patch("photoscribe.subprocess.run",
               return_value=make_completed_process(returncode=1, stderr="boom")):
        result = MetadataWriter.read_existing_metadata("/x.jpg")
    assert result == ("", "", [])


def test_read_existing_metadata_returns_empty_on_invalid_json():
    with patch("photoscribe.subprocess.run",
               return_value=make_completed_process(stdout="not json")):
        result = MetadataWriter.read_existing_metadata("/x.jpg")
    assert result == ("", "", [])


def test_read_existing_metadata_returns_empty_on_subprocess_exception():
    """The bare `except Exception` at line 278 swallows everything."""
    with patch("photoscribe.subprocess.run", side_effect=OSError("no exiftool")):
        result = MetadataWriter.read_existing_metadata("/x.jpg")
    assert result == ("", "", [])


def test_read_existing_metadata_handles_missing_fields():
    """exiftool omits keys for absent fields, not blank strings."""
    stdout = json.dumps([{}])
    with patch("photoscribe.subprocess.run",
               return_value=make_completed_process(stdout=stdout)):
        result = MetadataWriter.read_existing_metadata("/x.jpg")
    assert result == ("", "", [])


# ─────────────────────────────────────────────────────────
# write_metadata — argv construction across the matrix
# ─────────────────────────────────────────────────────────

def _argv_of(call):
    """Pull the positional argv list out of a `subprocess.run` call."""
    return call.args[0]


@pytest.fixture
def metadata():
    return PhotoMetadata(title="My Title", caption="My Caption",
                         keywords=["alpha", "beta"])


def test_write_metadata_default_includes_iptc_xmp_exif_fields(metadata):
    """Default mode (replace + backup) writes title/caption to all three
    metadata namespaces — the load-bearing 'belt and braces' the CLAUDE.md
    note calls out."""
    with patch("photoscribe.subprocess.run",
               return_value=make_completed_process()) as run:
        MetadataWriter.write_metadata("/x.jpg", metadata)
    write_argv = _argv_of(run.call_args_list[-1])
    assert "-IPTC:ObjectName=My Title" in write_argv
    assert "-XMP:Title=My Title" in write_argv
    assert "-IPTC:Caption-Abstract=My Caption" in write_argv
    assert "-XMP:Description=My Caption" in write_argv
    assert "-EXIF:ImageDescription=My Caption" in write_argv


def test_write_metadata_default_uses_backup(metadata):
    """backup=True is the default; -overwrite_original must NOT appear."""
    with patch("photoscribe.subprocess.run",
               return_value=make_completed_process()) as run:
        MetadataWriter.write_metadata("/x.jpg", metadata)
    for call in run.call_args_list:
        assert "-overwrite_original" not in _argv_of(call)


def test_write_metadata_no_backup_adds_overwrite_original(metadata):
    with patch("photoscribe.subprocess.run",
               return_value=make_completed_process()) as run:
        MetadataWriter.write_metadata("/x.jpg", metadata, backup=False)
    # Both the clear pass and the write pass must include -overwrite_original.
    for call in run.call_args_list:
        assert "-overwrite_original" in _argv_of(call)


def test_write_metadata_replace_mode_clears_keywords_first(metadata):
    """In replace mode (append_keywords=False) the writer spawns TWO
    subprocesses: a clear pass for keywords, then the main write."""
    with patch("photoscribe.subprocess.run",
               return_value=make_completed_process()) as run:
        MetadataWriter.write_metadata("/x.jpg", metadata)
    assert run.call_count == 2
    clear_argv = _argv_of(run.call_args_list[0])
    assert "-IPTC:Keywords=" in clear_argv
    assert "-XMP:Subject=" in clear_argv


def test_write_metadata_replace_mode_writes_keywords_after_clearing(metadata):
    with patch("photoscribe.subprocess.run",
               return_value=make_completed_process()) as run:
        MetadataWriter.write_metadata("/x.jpg", metadata)
    write_argv = _argv_of(run.call_args_list[-1])
    assert "-IPTC:Keywords+=alpha" in write_argv
    assert "-IPTC:Keywords+=beta" in write_argv
    assert "-XMP:Subject+=alpha" in write_argv
    assert "-XMP:Subject+=beta" in write_argv


def test_write_metadata_append_mode_skips_clear_pass(metadata):
    """append_keywords=True must NOT run the keyword clear pass.

    Note: append mode still runs `read_existing_metadata` (one subprocess)
    so it can dedupe — total is 2 calls (read + write), not 3 like the
    skip_existing path. The thing under test here is the *absence* of the
    `-IPTC:Keywords=` clear argv, not the call count.
    """
    read_result = make_completed_process(stdout=json.dumps([{
        "ObjectName": "", "Caption-Abstract": "", "Keywords": [],
    }]))
    write_result = make_completed_process()
    with patch("photoscribe.subprocess.run",
               side_effect=[read_result, write_result]) as run:
        MetadataWriter.write_metadata("/x.jpg", metadata, append_keywords=True)
    assert run.call_count == 2
    # No call should contain the empty-RHS clear arg.
    for call in run.call_args_list:
        assert "-IPTC:Keywords=" not in _argv_of(call)
    write_argv = _argv_of(run.call_args_list[-1])
    assert "-IPTC:Keywords+=alpha" in write_argv
    assert "-IPTC:Keywords+=beta" in write_argv


def test_write_metadata_append_mode_dedupes_against_existing():
    """append_keywords=True calls read_existing_metadata first and skips
    keywords (case-insensitive) that are already present."""
    existing = json.dumps([{
        "ObjectName": "", "Caption-Abstract": "", "Keywords": ["Alpha"],
    }])
    write_result = make_completed_process()
    read_result = make_completed_process(stdout=existing)

    metadata = PhotoMetadata(title="t", caption="c", keywords=["alpha", "beta"])

    with patch("photoscribe.subprocess.run",
               side_effect=[read_result, write_result]) as run:
        MetadataWriter.write_metadata("/x.jpg", metadata, append_keywords=True)
    write_argv = _argv_of(run.call_args_list[-1])
    assert "-IPTC:Keywords+=beta" in write_argv
    assert not any(arg.endswith("=alpha") or arg.endswith("=Alpha")
                   for arg in write_argv)


def test_write_metadata_skip_existing_omits_title_when_present():
    """skip_existing=True with append_keywords=False spawns 3 subprocesses:
    read existing, clear-keywords pass, then the main write."""
    existing = json.dumps([{
        "ObjectName": "Pre-existing title",
        "Caption-Abstract": "",
        "Keywords": [],
    }])
    metadata = PhotoMetadata(title="New title", caption="New caption", keywords=[])

    read_result = make_completed_process(stdout=existing)
    clear_result = make_completed_process()
    write_result = make_completed_process()

    with patch("photoscribe.subprocess.run",
               side_effect=[read_result, clear_result, write_result]) as run:
        MetadataWriter.write_metadata("/x.jpg", metadata, skip_existing=True)
    write_argv = _argv_of(run.call_args_list[-1])
    assert not any(arg.startswith("-IPTC:ObjectName=") for arg in write_argv)
    assert not any(arg.startswith("-XMP:Title=") for arg in write_argv)
    # Caption was empty in existing → still gets written.
    assert "-IPTC:Caption-Abstract=New caption" in write_argv


def test_write_metadata_skip_existing_writes_when_field_empty():
    """Mirror of above: when the existing field is blank, the write proceeds."""
    existing = json.dumps([{
        "ObjectName": "",  # empty → skip_existing should not block
        "Caption-Abstract": "",
        "Keywords": [],
    }])
    metadata = PhotoMetadata(title="New title", caption="c", keywords=[])

    read_result = make_completed_process(stdout=existing)
    clear_result = make_completed_process()
    write_result = make_completed_process()

    with patch("photoscribe.subprocess.run",
               side_effect=[read_result, clear_result, write_result]) as run:
        MetadataWriter.write_metadata("/x.jpg", metadata, skip_existing=True)
    write_argv = _argv_of(run.call_args_list[-1])
    assert "-IPTC:ObjectName=New title" in write_argv


def test_write_metadata_raises_on_exiftool_error(metadata):
    failed = make_completed_process(returncode=1, stderr="exiftool died")
    with patch("photoscribe.subprocess.run", return_value=failed), \
         pytest.raises(RuntimeError, match="exiftool died"):
        MetadataWriter.write_metadata("/x.jpg", metadata)


def test_write_metadata_filepath_is_last_arg(metadata):
    with patch("photoscribe.subprocess.run",
               return_value=make_completed_process()) as run:
        MetadataWriter.write_metadata("/some/path/x.jpg", metadata)
    write_argv = _argv_of(run.call_args_list[-1])
    assert write_argv[-1] == "/some/path/x.jpg"


def test_write_metadata_returns_true_on_success(metadata):
    with patch("photoscribe.subprocess.run",
               return_value=make_completed_process()):
        assert MetadataWriter.write_metadata("/x.jpg", metadata) is True


# ─────────────────────────────────────────────────────────
# check_exiftool — thin wrapper, single behaviour smoke
# ─────────────────────────────────────────────────────────

def test_check_exiftool_true_when_present():
    with patch("photoscribe.shutil.which", return_value="/usr/local/bin/exiftool"):
        assert MetadataWriter.check_exiftool() is True


def test_check_exiftool_false_when_missing():
    with patch("photoscribe.shutil.which", return_value=None):
        assert MetadataWriter.check_exiftool() is False
