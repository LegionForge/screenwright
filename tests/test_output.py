from __future__ import annotations

import json
from pathlib import Path

from screenwright.capture import CaptureResult, FlowResult
from screenwright.output import (
    _escape_markdown_cell,
    save_metadata,
    write_flow_output,
    write_root_readme,
)
from screenwright.vision import ScreenshotMetadata


def _make_capture(tmp_path: Path, flow_name: str, name: str, metadata=None) -> CaptureResult:
    path = tmp_path / flow_name / f"{name}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fake-png-bytes")
    return CaptureResult(flow_name=flow_name, capture_name=name, path=path, metadata=metadata)


def test_save_metadata_writes_json_sidecar(tmp_path):
    metadata = ScreenshotMetadata(description="A login form", components=["form", "input"])
    capture = _make_capture(tmp_path, "login", "login-empty", metadata=metadata)

    json_path = save_metadata(capture, tmp_path)

    assert json_path == capture.path.with_suffix(".json")
    data = json.loads(json_path.read_text())
    assert data["description"] == "A login form"
    assert data["components"] == ["form", "input"]


def test_save_metadata_returns_none_without_metadata(tmp_path):
    capture = _make_capture(tmp_path, "login", "login-empty", metadata=None)
    assert save_metadata(capture, tmp_path) is None


def test_write_flow_output_creates_index_and_sidecars(tmp_path):
    metadata = ScreenshotMetadata(description="Homepage hero")
    capture = _make_capture(tmp_path, "homepage", "homepage-full", metadata=metadata)
    result = FlowResult(flow_name="homepage", captures=[capture])

    index_path = write_flow_output(result, tmp_path)

    assert index_path.exists()
    content = index_path.read_text()
    assert "homepage-full.png" in content
    assert "Homepage hero" in content
    assert capture.path.with_suffix(".json").exists()


def test_write_flow_output_handles_missing_metadata(tmp_path):
    capture = _make_capture(tmp_path, "homepage", "homepage-full", metadata=None)
    result = FlowResult(flow_name="homepage", captures=[capture])

    index_path = write_flow_output(result, tmp_path)

    content = index_path.read_text()
    assert "| ![](homepage-full.png) |  |" in content
    assert not capture.path.with_suffix(".json").exists()


def test_write_flow_output_links_accessibility_snapshot(tmp_path):
    capture = _make_capture(tmp_path, "homepage", "homepage-full", metadata=None)
    capture.accessibility_path = tmp_path / "homepage" / "homepage-full.aria.yaml"

    result = FlowResult(flow_name="homepage", captures=[capture])
    index_path = write_flow_output(result, tmp_path)

    content = index_path.read_text()
    assert "[a11y](homepage-full.aria.yaml)" in content


def test_write_flow_output_links_pdf(tmp_path):
    capture = _make_capture(tmp_path, "homepage", "homepage-full", metadata=None)
    capture.pdf_path = tmp_path / "homepage" / "homepage-full.pdf"

    result = FlowResult(flow_name="homepage", captures=[capture])
    index_path = write_flow_output(result, tmp_path)

    content = index_path.read_text()
    assert "[pdf](homepage-full.pdf)" in content


def test_escape_markdown_cell_strips_html_tags():
    assert _escape_markdown_cell('a <img src=x onerror="alert(1)"> b') == "a  b"


def test_escape_markdown_cell_escapes_pipes_and_backslashes():
    assert _escape_markdown_cell("a | b \\ c") == r"a \| b \\ c"


def test_escape_markdown_cell_collapses_newlines():
    assert _escape_markdown_cell("line one\nline two") == "line one line two"


def test_escape_markdown_cell_caps_length():
    long_text = "x" * 1000
    result = _escape_markdown_cell(long_text)
    assert len(result) <= 500
    assert result.endswith("…")


def test_write_flow_output_escapes_malicious_description(tmp_path):
    metadata = ScreenshotMetadata(
        description="Login form | <script>alert(1)</script> broken | table"
    )
    capture = _make_capture(tmp_path, "login", "login-empty", metadata=metadata)
    result = FlowResult(flow_name="login", captures=[capture])

    index_path = write_flow_output(result, tmp_path)
    content = index_path.read_text()

    assert "<script>" not in content
    # A 2-column row has exactly 3 structural pipes (leading, middle, trailing).
    # Strip escaped pipes first — every pipe that came from the description
    # must be escaped, leaving only the table's own delimiters behind.
    row = next(line for line in content.splitlines() if "login-empty.png" in line)
    assert row.replace("\\|", "").count("|") == 3


def test_write_root_readme_lists_all_flows(tmp_path):
    homepage = FlowResult(flow_name="homepage", captures=[_make_capture(tmp_path, "homepage", "a")])
    login = FlowResult(
        flow_name="login",
        captures=[_make_capture(tmp_path, "login", "a"), _make_capture(tmp_path, "login", "b")],
    )

    readme_path = write_root_readme([homepage, login], tmp_path)

    content = readme_path.read_text()
    assert "| homepage | 1 | ✅ | [homepage/index.md](homepage/index.md) |" in content
    assert "| login | 2 | ✅ | [login/index.md](login/index.md) |" in content


def test_write_root_readme_flags_partial_flow_status(tmp_path):
    ok = FlowResult(flow_name="homepage", captures=[_make_capture(tmp_path, "homepage", "a")])
    partial = FlowResult(
        flow_name="login",
        captures=[_make_capture(tmp_path, "login", "a")],
        error="Step 2 (capture) failed: Selector not found: '#missing'",
    )

    readme_path = write_root_readme([ok, partial], tmp_path)

    content = readme_path.read_text()
    assert "| homepage | 1 | ✅ | [homepage/index.md](homepage/index.md) |" in content
    assert "| login | 1 | ⚠️ Partial | [login/index.md](login/index.md) |" in content


def test_write_flow_output_shows_error_banner_when_flow_stopped_early(tmp_path):
    capture = _make_capture(tmp_path, "login", "login-empty", metadata=None)
    result = FlowResult(
        flow_name="login",
        captures=[capture],
        error="Step 2 (capture) failed: Selector not found: '#missing'",
    )

    index_path = write_flow_output(result, tmp_path)

    content = index_path.read_text()
    assert "⚠️ **Flow stopped early:**" in content
    assert "Selector not found: '#missing'" in content


def test_write_flow_output_omits_error_banner_on_success(tmp_path):
    capture = _make_capture(tmp_path, "login", "login-empty", metadata=None)
    result = FlowResult(flow_name="login", captures=[capture])

    index_path = write_flow_output(result, tmp_path)

    assert "⚠️" not in index_path.read_text()
