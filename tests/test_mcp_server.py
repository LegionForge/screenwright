from __future__ import annotations

from pathlib import Path

import pytest

from screenwright.mcp_server import _resolve_capture_path, run_flow_tool


def test_resolve_capture_path_accepts_safe_name(tmp_path):
    result = _resolve_capture_path(tmp_path, "homepage-full")
    assert result == (tmp_path / "homepage-full.png").resolve()


@pytest.mark.parametrize(
    "malicious_name",
    [
        "../../../../etc/passwd",
        "..",
        "foo/../../bar",
        "/etc/passwd",
        "a/b",
    ],
)
def test_resolve_capture_path_rejects_traversal(tmp_path, malicious_name):
    with pytest.raises(ValueError):
        _resolve_capture_path(tmp_path, malicious_name)


def test_resolve_capture_path_stays_inside_output_root(tmp_path):
    result = _resolve_capture_path(tmp_path, "safe-name")
    assert Path(result).resolve().is_relative_to(tmp_path.resolve())


@pytest.mark.integration
def test_run_flow_tool_returns_partial_result_dict_on_step_failure(tmp_path):
    html = tmp_path / "page.html"
    html.write_text("<!doctype html><html><body><h1>hi</h1></body></html>")
    url = f"file://{html}"

    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        f"""
        [screenwright]
        base_url = ""

        [[flows]]
        name = "flaky"

          [[flows.steps]]
          action = "navigate"
          url = "{url}"

          [[flows.steps]]
          action = "capture"
          name = "ok"

          [[flows.steps]]
          action = "capture"
          name = "missing"
          selector = "#nope"
        """
    )

    import asyncio

    output = asyncio.run(
        run_flow_tool("flaky", config_path=str(toml_path), output_dir=str(tmp_path / "out"))
    )

    assert isinstance(output, dict)
    assert len(output["captures"]) == 1
    assert output["failed_step_index"] == 2
    assert output["error"] is not None
    assert output["video_path"] is None
