from __future__ import annotations

import shutil

import pytest

from screenwright.capture import _resolve_fill_value, capture_single_url, run_flow
from screenwright.config import load_config

pytestmark = pytest.mark.integration


def test_resolve_fill_value_passes_through_literals():
    assert _resolve_fill_value("demo@example.com") == "demo@example.com"


def test_resolve_fill_value_resolves_env_ref(monkeypatch):
    monkeypatch.setenv("SCREENWRIGHT_TEST_VAR", "resolved-secret")
    assert _resolve_fill_value("${SCREENWRIGHT_TEST_VAR}") == "resolved-secret"


def test_resolve_fill_value_raises_on_unset_env_var(monkeypatch):
    monkeypatch.delenv("SCREENWRIGHT_TEST_VAR_UNSET", raising=False)
    with pytest.raises(ValueError, match="SCREENWRIGHT_TEST_VAR_UNSET"):
        _resolve_fill_value("${SCREENWRIGHT_TEST_VAR_UNSET}")


_HTML = """
<!doctype html>
<html>
<head><title>Test Page</title></head>
<body>
  <h1>Hello Screenwright</h1>
  <form id="login">
    <input id="email" type="email">
    <button id="submit-btn" type="submit">Sign In</button>
  </form>
  <input id="remember-me" type="checkbox">
  <select id="country">
    <option value="us">United States</option>
    <option value="ca">Canada</option>
  </select>
</body>
</html>
"""


def _write_page(tmp_path):
    page = tmp_path / "page.html"
    page.write_text(_HTML)
    return f"file://{page}"


def test_capture_single_url_full_page(tmp_path):
    url = _write_page(tmp_path)
    out = tmp_path / "out" / "full.png"

    import asyncio

    result_path = asyncio.run(capture_single_url(url, out))

    assert result_path == out
    assert out.exists()
    assert out.stat().st_size > 0


def test_capture_single_url_element(tmp_path):
    url = _write_page(tmp_path)
    out = tmp_path / "out" / "element.png"

    import asyncio

    asyncio.run(capture_single_url(url, out, selector="#login"))

    assert out.exists()
    assert out.stat().st_size > 0


def test_capture_single_url_missing_selector_raises(tmp_path):
    url = _write_page(tmp_path)
    out = tmp_path / "out" / "missing.png"

    import asyncio

    with pytest.raises(ValueError, match="Selector not found"):
        asyncio.run(capture_single_url(url, out, selector="#does-not-exist"))


def test_run_flow_executes_steps_and_produces_captures(tmp_path):
    url = _write_page(tmp_path)
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        f"""
        [screenwright]
        base_url = ""

        [[flows]]
        name = "login"

          [[flows.steps]]
          action = "navigate"
          url = "{url}"

          [[flows.steps]]
          action = "capture"
          name = "login-empty"

          [[flows.steps]]
          action = "fill"
          selector = "#email"
          value = "test@example.com"

          [[flows.steps]]
          action = "capture"
          name = "login-filled"
          selector = "#login"
        """
    )
    cfg = load_config(toml_path)
    flow = cfg.get_flow("login")
    output_root = tmp_path / "output"

    import asyncio

    result = asyncio.run(run_flow(flow, cfg, output_root))

    assert result.flow_name == "login"
    assert len(result.captures) == 2
    assert result.captures[0].capture_name == "login-empty"
    assert result.captures[0].path.exists()
    assert result.captures[1].capture_name == "login-filled"
    assert result.captures[1].path.exists()


def test_run_flow_with_recording_produces_video(tmp_path):
    url = _write_page(tmp_path)
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        f"""
        [screenwright]
        base_url = ""

        [[flows]]
        name = "demo"
        record = true

          [[flows.steps]]
          action = "navigate"
          url = "{url}"

          [[flows.steps]]
          action = "fill"
          selector = "#email"
          value = "test@example.com"
        """
    )
    cfg = load_config(toml_path)
    flow = cfg.get_flow("demo")
    output_root = tmp_path / "output"

    import asyncio

    result = asyncio.run(run_flow(flow, cfg, output_root))

    assert result.video_path is not None
    assert result.video_path.name == "demo.webm"
    assert result.video_path.exists()
    assert result.video_path.stat().st_size > 0


def test_run_flow_without_recording_has_no_video(tmp_path):
    url = _write_page(tmp_path)
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        f"""
        [screenwright]
        base_url = ""

        [[flows]]
        name = "no-record"

          [[flows.steps]]
          action = "navigate"
          url = "{url}"

          [[flows.steps]]
          action = "capture"
          name = "shot"
        """
    )
    cfg = load_config(toml_path)
    flow = cfg.get_flow("no-record")
    output_root = tmp_path / "output"

    import asyncio

    result = asyncio.run(run_flow(flow, cfg, output_root))

    assert result.video_path is None


def test_run_flow_step_failure_returns_partial_result_not_exception(tmp_path):
    url = _write_page(tmp_path)
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
          name = "before-failure"

          [[flows.steps]]
          action = "capture"
          name = "missing-selector"
          selector = "#does-not-exist"

          [[flows.steps]]
          action = "capture"
          name = "after-failure"
        """
    )
    cfg = load_config(toml_path)
    flow = cfg.get_flow("flaky")
    output_root = tmp_path / "output"

    import asyncio

    result = asyncio.run(run_flow(flow, cfg, output_root))

    # The step before the failure succeeded and is preserved, not discarded.
    assert len(result.captures) == 1
    assert result.captures[0].capture_name == "before-failure"
    assert result.captures[0].path.exists()

    # The step after the failure never ran.
    assert not (output_root / "flaky" / "after-failure.png").exists()

    # Failure is reported on the result, not raised as an exception.
    assert result.failed_step_index == 2
    assert "missing-selector" not in [c.capture_name for c in result.captures]
    assert result.error is not None
    assert "Selector not found" in result.error


def test_run_flow_with_recording_finalizes_video_on_step_failure(tmp_path):
    url = _write_page(tmp_path)
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        f"""
        [screenwright]
        base_url = ""

        [[flows]]
        name = "flaky-recorded"
        record = true

          [[flows.steps]]
          action = "navigate"
          url = "{url}"

          [[flows.steps]]
          action = "capture"
          name = "missing-selector"
          selector = "#does-not-exist"
        """
    )
    cfg = load_config(toml_path)
    flow = cfg.get_flow("flaky-recorded")
    output_root = tmp_path / "output"

    import asyncio

    result = asyncio.run(run_flow(flow, cfg, output_root))

    assert result.error is not None
    # The video must still be flushed to disk even though a step failed —
    # Playwright only finalizes the file on context.close(), so skipping
    # cleanup on the error path would silently lose the whole recording.
    assert result.video_path is not None
    assert result.video_path.exists()
    assert result.video_path.stat().st_size > 0


def test_run_flow_fill_resolves_env_var_reference(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREENWRIGHT_TEST_EMAIL", "resolved@example.com")
    url = _write_page(tmp_path)
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        f"""
        [screenwright]
        base_url = ""

        [[flows]]
        name = "login-env"

          [[flows.steps]]
          action = "navigate"
          url = "{url}"

          [[flows.steps]]
          action = "fill"
          selector = "#email"
          value = "${{SCREENWRIGHT_TEST_EMAIL}}"
          secret = true

          [[flows.steps]]
          action = "capture"
          name = "login-filled"
          selector = "#login"
        """
    )
    cfg = load_config(toml_path)
    flow = cfg.get_flow("login-env")
    output_root = tmp_path / "output"

    import asyncio

    result = asyncio.run(run_flow(flow, cfg, output_root))

    assert result.error is None
    assert len(result.captures) == 1


def test_run_flow_fill_reports_clear_error_on_unset_env_var(tmp_path, monkeypatch):
    monkeypatch.delenv("SCREENWRIGHT_TEST_MISSING_VAR", raising=False)
    url = _write_page(tmp_path)
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        f"""
        [screenwright]
        base_url = ""

        [[flows]]
        name = "login-missing-env"

          [[flows.steps]]
          action = "navigate"
          url = "{url}"

          [[flows.steps]]
          action = "fill"
          selector = "#email"
          value = "${{SCREENWRIGHT_TEST_MISSING_VAR}}"
        """
    )
    cfg = load_config(toml_path)
    flow = cfg.get_flow("login-missing-env")
    output_root = tmp_path / "output"

    import asyncio

    result = asyncio.run(run_flow(flow, cfg, output_root))

    assert result.error is not None
    assert "SCREENWRIGHT_TEST_MISSING_VAR" in result.error
    assert result.failed_step_index == 1


def test_run_flow_check_and_select_steps(tmp_path):
    url = _write_page(tmp_path)
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        f"""
        [screenwright]
        base_url = ""

        [[flows]]
        name = "interactive"

          [[flows.steps]]
          action = "navigate"
          url = "{url}"

          [[flows.steps]]
          action = "check"
          selector = "#remember-me"

          [[flows.steps]]
          action = "select"
          selector = "#country"
          value = "ca"

          [[flows.steps]]
          action = "hover"
          selector = "#submit-btn"

          [[flows.steps]]
          action = "capture"
          name = "interactive-state"
        """
    )
    cfg = load_config(toml_path)
    flow = cfg.get_flow("interactive")
    output_root = tmp_path / "output"

    import asyncio

    result = asyncio.run(run_flow(flow, cfg, output_root))

    assert len(result.captures) == 1
    assert result.captures[0].path.exists()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="requires ffmpeg on PATH")
def test_run_flow_with_mp4_conversion(tmp_path):
    url = _write_page(tmp_path)
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        f"""
        [screenwright]
        base_url = ""

        [[flows]]
        name = "demo-mp4"
        record = true
        record_mp4 = true

          [[flows.steps]]
          action = "navigate"
          url = "{url}"
        """
    )
    cfg = load_config(toml_path)
    flow = cfg.get_flow("demo-mp4")
    output_root = tmp_path / "output"

    import asyncio

    result = asyncio.run(run_flow(flow, cfg, output_root))

    assert result.video_path is not None
    assert result.video_mp4_path is not None
    assert result.video_mp4_path.name == "demo-mp4.mp4"
    assert result.video_mp4_path.exists()
    assert result.video_mp4_path.stat().st_size > 0
