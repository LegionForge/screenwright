from __future__ import annotations

from pathlib import Path

import pytest

from screenwright.config import ScreenwrightConfig
from screenwright.mcp_server import (
    _DEFAULT_OUTPUT,
    _resolve_capture_path,
    _resolve_output,
    describe_screenshot,
    run_flow_tool,
)


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


def test_resolve_output_prefers_explicit_override():
    cfg = ScreenwrightConfig()
    assert _resolve_output(cfg, "/tmp/explicit-override") == Path("/tmp/explicit-override")


def test_resolve_output_falls_back_to_default_when_output_dir_never_set():
    cfg = ScreenwrightConfig()
    assert "output_dir" not in cfg.model_fields_set
    assert _resolve_output(cfg, None) == _DEFAULT_OUTPUT


def test_resolve_output_respects_explicitly_set_value_matching_the_default():
    # This is the bug: a user who deliberately writes
    # `output_dir = "docs/screenshots"` in their TOML (same string as the
    # field default) must still get that directory — not get silently
    # redirected to a temp dir just because the value happens to match the
    # default.
    cfg = ScreenwrightConfig.model_validate({"output_dir": "docs/screenshots"})
    assert "output_dir" in cfg.model_fields_set
    assert _resolve_output(cfg, None) == Path("docs/screenshots")


def test_resolve_output_respects_explicitly_set_custom_value():
    cfg = ScreenwrightConfig.model_validate({"output_dir": "custom/path"})
    assert _resolve_output(cfg, None) == Path("custom/path")


def test_describe_screenshot_raises_when_file_missing(tmp_path):
    import asyncio

    missing = tmp_path / "does-not-exist.png"
    with pytest.raises(FileNotFoundError):
        asyncio.run(describe_screenshot(str(missing)))


def test_describe_screenshot_returns_structured_json(tmp_path, monkeypatch):
    import asyncio

    from screenwright.vision import ScreenshotMetadata

    png = tmp_path / "shot.png"
    png.write_bytes(b"fake-png")

    def fake_describe(image_path, cfg):
        return ScreenshotMetadata(description="A login form", components=["form"])

    monkeypatch.setattr("screenwright.vision.describe", fake_describe)

    result = asyncio.run(describe_screenshot(str(png), structured_metadata=True))

    assert isinstance(result, str)
    assert "A login form" in result
    assert "form" in result


def test_describe_screenshot_returns_plain_description(tmp_path, monkeypatch):
    import asyncio

    from screenwright.vision import ScreenshotMetadata

    png = tmp_path / "shot.png"
    png.write_bytes(b"fake-png")

    def fake_describe(image_path, cfg):
        return ScreenshotMetadata(description="A login form")

    monkeypatch.setattr("screenwright.vision.describe", fake_describe)

    result = asyncio.run(describe_screenshot(str(png), structured_metadata=False))

    assert result == "A login form"
