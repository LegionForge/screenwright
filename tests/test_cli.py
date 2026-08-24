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


def test_run_exits_nonzero_when_a_flow_fails(tmp_path):
    # screenwright run is explicitly marketed (README) as usable in a CI
    # pre-flight check — a non-zero exit code is the only signal CI
    # actually gates on. A flow that stops mid-way (a bad selector here)
    # must fail the run, not just print a warning and exit 0.
    html = tmp_path / "page.html"
    html.write_text(_HTML)
    url = f"file://{html}"

    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        f"""
        [screenwright]
        base_url = ""

        [[flows]]
        name = "demo"

          [[flows.steps]]
          action = "navigate"
          url = "{url}"

          [[flows.steps]]
          action = "capture"
          name = "shot"
          selector = "#does-not-exist-anywhere"
        """
    )
    output_dir = tmp_path / "out"

    result = runner.invoke(app, ["run", str(toml_path), "--output", str(output_dir)])

    assert result.exit_code == 1
    assert "stopped early" in result.output


def test_run_reports_write_flow_output_failure_instead_of_a_raw_traceback(tmp_path, monkeypatch):
    # A failure writing index.md/.json sidecars (disk full, permission
    # denied) must not crash the whole run command with an unhandled
    # exception and lose every already-captured screenshot — it must be
    # reported the same clean way a step/setup/finalize failure already is.
    def broken_write_flow_output(_result, _output_root):
        raise OSError("simulated disk error writing flow output")

    monkeypatch.setattr("screenwright.cli.write_flow_output", broken_write_flow_output)

    html = tmp_path / "page.html"
    html.write_text(_HTML)
    url = f"file://{html}"

    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        f"""
        [screenwright]
        base_url = ""

        [[flows]]
        name = "demo"

          [[flows.steps]]
          action = "navigate"
          url = "{url}"

          [[flows.steps]]
          action = "capture"
          name = "shot"
        """
    )
    output_dir = tmp_path / "out"

    result = runner.invoke(app, ["run", str(toml_path), "--output", str(output_dir)])

    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert "stopped early" in result.output
    assert "simulated disk error" in result.output
    # The capture itself still succeeded and is still on disk — only the
    # output-writing step failed.
    assert (output_dir / "demo" / "shot.png").exists()


def test_run_reports_write_root_readme_failure_instead_of_a_raw_traceback(tmp_path, monkeypatch):
    def broken_write_root_readme(_results, _output_root):
        raise OSError("simulated disk error writing root README")

    monkeypatch.setattr("screenwright.cli.write_root_readme", broken_write_root_readme)

    html = tmp_path / "page.html"
    html.write_text(_HTML)
    url = f"file://{html}"

    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        f"""
        [screenwright]
        base_url = ""

        [[flows]]
        name = "demo"

          [[flows.steps]]
          action = "navigate"
          url = "{url}"

          [[flows.steps]]
          action = "capture"
          name = "shot"
        """
    )
    output_dir = tmp_path / "out"

    result = runner.invoke(app, ["run", str(toml_path), "--output", str(output_dir)])

    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert "Failed to write root README" in result.output
    assert "simulated disk error" in result.output
    # The flow itself still succeeded and its own output was still written —
    # only the root README failed.
    assert (output_dir / "demo" / "shot.png").exists()
    assert (output_dir / "demo" / "index.md").exists()


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


def _write_single_capture_config(tmp_path, html_path):
    url = f"file://{html_path}"
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        f"""
        [screenwright]
        base_url = ""
        vision_describe = false

        [[flows]]
        name = "demo"

          [[flows.steps]]
          action = "navigate"
          url = "{url}"

          [[flows.steps]]
          action = "capture"
          name = "shot"
        """
    )
    return toml_path


def test_check_reports_all_captures_as_changed_on_first_run(tmp_path):
    html = tmp_path / "page.html"
    html.write_text(_HTML)
    toml_path = _write_single_capture_config(tmp_path, html)
    output_dir = tmp_path / "out"

    result = runner.invoke(app, ["run", str(toml_path), "--output", str(output_dir), "--check"])

    assert result.exit_code == 1
    assert "demo/shot" in result.output


def test_check_reports_no_changes_on_identical_rerun(tmp_path):
    html = tmp_path / "page.html"
    html.write_text(_HTML)
    toml_path = _write_single_capture_config(tmp_path, html)
    output_dir = tmp_path / "out"

    first = runner.invoke(app, ["run", str(toml_path), "--output", str(output_dir), "--check"])
    assert first.exit_code == 1

    second = runner.invoke(app, ["run", str(toml_path), "--output", str(output_dir), "--check"])
    assert second.exit_code == 0
    assert "No screenshot changes detected" in second.output


def test_check_reports_changed_capture_after_content_change(tmp_path):
    html = tmp_path / "page.html"
    html.write_text(_HTML)
    toml_path = _write_single_capture_config(tmp_path, html)
    output_dir = tmp_path / "out"

    first = runner.invoke(app, ["run", str(toml_path), "--output", str(output_dir), "--check"])
    assert first.exit_code == 1

    html.write_text(_HTML.replace("Hello", "Goodbye"))
    second = runner.invoke(app, ["run", str(toml_path), "--output", str(output_dir), "--check"])
    assert second.exit_code == 1
    assert "demo/shot" in second.output


def test_run_without_check_does_not_print_diff_report(tmp_path):
    html = tmp_path / "page.html"
    html.write_text(_HTML)
    toml_path = _write_single_capture_config(tmp_path, html)
    output_dir = tmp_path / "out"

    result = runner.invoke(app, ["run", str(toml_path), "--output", str(output_dir)])

    assert result.exit_code == 0
    assert "screenshot changes" not in result.output.lower()


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
