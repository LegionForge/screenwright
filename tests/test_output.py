from __future__ import annotations

import json
from pathlib import Path

from screenwright.capture import CaptureResult, FlowResult
from screenwright.output import save_metadata, write_flow_output, write_root_readme
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


def test_write_root_readme_lists_all_flows(tmp_path):
    homepage = FlowResult(flow_name="homepage", captures=[_make_capture(tmp_path, "homepage", "a")])
    login = FlowResult(
        flow_name="login",
        captures=[_make_capture(tmp_path, "login", "a"), _make_capture(tmp_path, "login", "b")],
    )

    readme_path = write_root_readme([homepage, login], tmp_path)

    content = readme_path.read_text()
    assert "| homepage | 1 | [homepage/index.md](homepage/index.md) |" in content
    assert "| login | 2 | [login/index.md](login/index.md) |" in content
