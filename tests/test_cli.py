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


def _write_two_flow_config(tmp_path):
    html = tmp_path / "page.html"
    html.write_text(_HTML)
    url = f"file://{html}"

    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        f"""
        [screenwright]
        base_url = ""

        [[flows]]
        name = "alpha"

          [[flows.steps]]
          action = "navigate"
          url = "{url}"

          [[flows.steps]]
          action = "capture"
          name = "shot"

        [[flows]]
        name = "beta"

          [[flows.steps]]
          action = "navigate"
          url = "{url}"

          [[flows.steps]]
          action = "capture"
          name = "shot"
        """
    )
    return toml_path


def test_run_rejects_concurrency_below_one(tmp_path):
    toml_path = _write_two_flow_config(tmp_path)
    result = runner.invoke(app, ["run", str(toml_path), "--concurrency", "0"])
    assert result.exit_code == 1
    assert "--concurrency must be at least 1" in result.output


@pytest.mark.parametrize("concurrency", [1, 2])
def test_run_completes_all_flows_at_various_concurrency(tmp_path, concurrency):
    toml_path = _write_two_flow_config(tmp_path)
    output_dir = tmp_path / "out"

    result = runner.invoke(
        app,
        ["run", str(toml_path), "--output", str(output_dir), "--concurrency", str(concurrency)],
    )

    assert result.exit_code == 0
    assert (output_dir / "alpha" / "shot.png").exists()
    assert (output_dir / "beta" / "shot.png").exists()
    root_readme = (output_dir / "README.md").read_text()
    assert "alpha" in root_readme
    assert "beta" in root_readme


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
