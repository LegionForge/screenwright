from __future__ import annotations

import pytest
from typer.testing import CliRunner

from screenwright.cli import app
from screenwright.vision import ScreenshotMetadata

pytestmark = pytest.mark.integration

runner = CliRunner()

_HTML = """
<!doctype html>
<html><head><title>Test</title></head>
<body><h1>Hello</h1></body></html>
"""


def _write_two_capture_flow(tmp_path):
    html = tmp_path / "page.html"
    html.write_text(_HTML)
    url = f"file://{html}"

    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        f"""
        [screenwright]
        base_url = ""

        [vision]
        provider = "anthropic"

        [[flows]]
        name = "demo"

          [[flows.steps]]
          action = "navigate"
          url = "{url}"

          [[flows.steps]]
          action = "capture"
          name = "first"

          [[flows.steps]]
          action = "capture"
          name = "second"
        """
    )
    return toml_path


def test_run_continues_past_a_single_describe_failure(tmp_path, monkeypatch):
    toml_path = _write_two_capture_flow(tmp_path)
    output_dir = tmp_path / "out"

    calls = {"count": 0}

    def fake_describe(image_path, cfg):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("simulated vision API outage")
        return ScreenshotMetadata(description="second capture described fine")

    monkeypatch.setattr("screenwright.cli.describe", fake_describe)

    result = runner.invoke(app, ["run", str(toml_path), "--output", str(output_dir)])

    assert result.exit_code == 0
    # Both captures are still on disk and indexed even though describing
    # the first one failed.
    assert (output_dir / "demo" / "first.png").exists()
    assert (output_dir / "demo" / "second.png").exists()
    index_content = (output_dir / "demo" / "index.md").read_text()
    assert "second capture described fine" in index_content
    assert "Warning" in result.output
