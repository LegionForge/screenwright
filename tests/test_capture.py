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


def _png_dimensions(path):
    # PNG signature (8 bytes) + IHDR chunk length/type (8 bytes), then
    # width/height as big-endian uint32 — avoids adding an image-library
    # dependency just to assert a screenshot's viewport size in tests.
    data = path.read_bytes()
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    return width, height


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


def test_capture_single_url_respects_custom_viewport(tmp_path):
    url = _write_page(tmp_path)
    out = tmp_path / "out" / "viewport.png"

    import asyncio

    asyncio.run(capture_single_url(url, out, viewport_width=600, viewport_height=400))

    width, _height = _png_dimensions(out)
    assert width == 600


def test_capture_single_url_default_viewport_matches_playwright_default(tmp_path):
    # Not setting viewport_width/height explicitly must behave exactly as
    # before this feature existed — Playwright's own Chromium default is
    # 1280x720, which is also this function's default, so this asserts no
    # behavior change for existing callers.
    url = _write_page(tmp_path)
    out = tmp_path / "out" / "default-viewport.png"

    import asyncio

    asyncio.run(capture_single_url(url, out))

    width, _height = _png_dimensions(out)
    assert width == 1280


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


def test_run_flow_with_har_records_network_traffic(tmp_path):
    url = _write_page(tmp_path)
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        f"""
        [screenwright]
        base_url = ""

        [[flows]]
        name = "har-flow"
        har = true

          [[flows.steps]]
          action = "navigate"
          url = "{url}"

          [[flows.steps]]
          action = "capture"
          name = "shot"
        """
    )
    cfg = load_config(toml_path)
    flow = cfg.get_flow("har-flow")
    output_root = tmp_path / "output"

    import asyncio

    result = asyncio.run(run_flow(flow, cfg, output_root))

    assert result.error is None
    assert result.har_path is not None
    assert result.har_path == output_root / "har-flow" / "har-flow.har"
    assert result.har_path.exists()
    assert result.har_path.stat().st_size > 0
    # HAR is JSON — at minimum it must parse and have the top-level "log" key.
    import json

    har_data = json.loads(result.har_path.read_text())
    assert "log" in har_data


def test_run_flow_without_har_produces_no_har_file(tmp_path):
    url = _write_page(tmp_path)
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        f"""
        [screenwright]
        base_url = ""

        [[flows]]
        name = "no-har"

          [[flows.steps]]
          action = "navigate"
          url = "{url}"

          [[flows.steps]]
          action = "capture"
          name = "shot"
        """
    )
    cfg = load_config(toml_path)
    flow = cfg.get_flow("no-har")
    output_root = tmp_path / "output"

    import asyncio

    result = asyncio.run(run_flow(flow, cfg, output_root))

    assert result.har_path is None
    assert not (output_root / "no-har" / "no-har.har").exists()


def test_run_flow_with_har_and_recording_together(tmp_path):
    url = _write_page(tmp_path)
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        f"""
        [screenwright]
        base_url = ""

        [[flows]]
        name = "har-and-video"
        har = true
        record = true

          [[flows.steps]]
          action = "navigate"
          url = "{url}"

          [[flows.steps]]
          action = "capture"
          name = "shot"
        """
    )
    cfg = load_config(toml_path)
    flow = cfg.get_flow("har-and-video")
    output_root = tmp_path / "output"

    import asyncio

    result = asyncio.run(run_flow(flow, cfg, output_root))

    assert result.error is None
    assert result.har_path is not None
    assert result.har_path.exists()
    assert result.video_path is not None
    assert result.video_path.exists()


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


def test_run_flow_respects_custom_viewport(tmp_path):
    url = _write_page(tmp_path)
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        f"""
        [screenwright]
        base_url = ""

        [[flows]]
        name = "sized"
        viewport_width = 600
        viewport_height = 400

          [[flows.steps]]
          action = "navigate"
          url = "{url}"

          [[flows.steps]]
          action = "capture"
          name = "shot"
        """
    )
    cfg = load_config(toml_path)
    flow = cfg.get_flow("sized")
    output_root = tmp_path / "output"

    import asyncio

    result = asyncio.run(run_flow(flow, cfg, output_root))

    width, _height = _png_dimensions(result.captures[0].path)
    assert width == 600


def test_run_flow_respects_custom_timeout(tmp_path):
    # A very short timeout on a step that has to wait for a selector that
    # never appears must fail fast with a Playwright TimeoutError surfaced
    # via the existing per-step error handling — not hang for the default
    # 30s. This is the actual behavioral proof that set_default_timeout
    # took effect, not just that the config field exists.
    url = _write_page(tmp_path)
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        f"""
        [screenwright]
        base_url = ""

        [[flows]]
        name = "impatient"
        timeout_ms = 200

          [[flows.steps]]
          action = "navigate"
          url = "{url}"

          [[flows.steps]]
          action = "click"
          selector = "#never-appears"
        """
    )
    cfg = load_config(toml_path)
    flow = cfg.get_flow("impatient")
    output_root = tmp_path / "output"

    import asyncio
    import time

    start = time.monotonic()
    result = asyncio.run(run_flow(flow, cfg, output_root))
    elapsed = time.monotonic() - start

    assert result.error is not None
    assert "Timeout" in result.error
    assert elapsed < 5  # well under the default 30s, proving timeout_ms took effect


def test_run_flow_with_valid_storage_state_succeeds(tmp_path):
    # An empty-but-well-formed storage_state (Playwright's own format) must
    # load without error — proves the plumbing (passed through to
    # browser.new_page/new_context) works, independent of whether it
    # actually contains a useful session for this test's blank page.
    import json

    storage_state_path = tmp_path / "state.json"
    storage_state_path.write_text(json.dumps({"cookies": [], "origins": []}))

    url = _write_page(tmp_path)
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        f"""
        [screenwright]
        base_url = ""

        [[flows]]
        name = "authed"
        storage_state = "{storage_state_path}"

          [[flows.steps]]
          action = "navigate"
          url = "{url}"

          [[flows.steps]]
          action = "capture"
          name = "shot"
        """
    )
    cfg = load_config(toml_path)
    flow = cfg.get_flow("authed")
    output_root = tmp_path / "output"

    import asyncio

    result = asyncio.run(run_flow(flow, cfg, output_root))

    assert result.error is None
    assert len(result.captures) == 1


def test_run_flow_with_missing_storage_state_reports_clean_error(tmp_path):
    # Session setup (including storage_state) happens before the step loop
    # — this proves a failure there is reported on the result like any
    # step failure, not raised as an unhandled exception out of run_flow.
    url = _write_page(tmp_path)
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        f"""
        [screenwright]
        base_url = ""

        [[flows]]
        name = "authed"
        storage_state = "{tmp_path / "does-not-exist.json"}"

          [[flows.steps]]
          action = "navigate"
          url = "{url}"
        """
    )
    cfg = load_config(toml_path)
    flow = cfg.get_flow("authed")
    output_root = tmp_path / "output"

    import asyncio

    result = asyncio.run(run_flow(flow, cfg, output_root))

    assert result.error is not None
    assert "Failed to start browser session" in result.error
    assert result.captures == []


def test_run_flow_with_malformed_storage_state_reports_clean_error(tmp_path):
    storage_state_path = tmp_path / "state.json"
    storage_state_path.write_text("not valid json at all")

    url = _write_page(tmp_path)
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        f"""
        [screenwright]
        base_url = ""

        [[flows]]
        name = "authed"
        storage_state = "{storage_state_path}"

          [[flows.steps]]
          action = "navigate"
          url = "{url}"
        """
    )
    cfg = load_config(toml_path)
    flow = cfg.get_flow("authed")
    output_root = tmp_path / "output"

    import asyncio

    result = asyncio.run(run_flow(flow, cfg, output_root))

    assert result.error is not None
    assert result.captures == []


def test_run_flow_writes_accessibility_snapshot_when_requested(tmp_path):
    url = _write_page(tmp_path)
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        f"""
        [screenwright]
        base_url = ""

        [[flows]]
        name = "a11y"

          [[flows.steps]]
          action = "navigate"
          url = "{url}"

          [[flows.steps]]
          action = "capture"
          name = "shot"
          accessibility_snapshot = true
        """
    )
    cfg = load_config(toml_path)
    flow = cfg.get_flow("a11y")
    output_root = tmp_path / "output"

    import asyncio

    result = asyncio.run(run_flow(flow, cfg, output_root))

    assert result.error is None
    capture = result.captures[0]
    assert capture.accessibility_path is not None
    assert capture.accessibility_path == output_root / "a11y" / "shot.aria.yaml"
    content = capture.accessibility_path.read_text()
    # The test page (see _HTML above) has an <h1>Hello Screenwright</h1>.
    assert "heading" in content
    assert "Hello Screenwright" in content


def test_run_flow_omits_accessibility_snapshot_by_default(tmp_path):
    url = _write_page(tmp_path)
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        f"""
        [screenwright]
        base_url = ""

        [[flows]]
        name = "no-a11y"

          [[flows.steps]]
          action = "navigate"
          url = "{url}"

          [[flows.steps]]
          action = "capture"
          name = "shot"
        """
    )
    cfg = load_config(toml_path)
    flow = cfg.get_flow("no-a11y")
    output_root = tmp_path / "output"

    import asyncio

    result = asyncio.run(run_flow(flow, cfg, output_root))

    assert result.captures[0].accessibility_path is None
    assert not (output_root / "no-a11y" / "shot.aria.yaml").exists()


def test_run_flow_writes_pdf_when_requested(tmp_path):
    url = _write_page(tmp_path)
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        f"""
        [screenwright]
        base_url = ""

        [[flows]]
        name = "pdf-flow"

          [[flows.steps]]
          action = "navigate"
          url = "{url}"

          [[flows.steps]]
          action = "capture"
          name = "shot"
          pdf = true
        """
    )
    cfg = load_config(toml_path)
    flow = cfg.get_flow("pdf-flow")
    output_root = tmp_path / "output"

    import asyncio

    result = asyncio.run(run_flow(flow, cfg, output_root))

    assert result.error is None
    capture = result.captures[0]
    assert capture.pdf_path is not None
    assert capture.pdf_path == output_root / "pdf-flow" / "shot.pdf"
    assert capture.pdf_path.exists()
    assert capture.pdf_path.read_bytes().startswith(b"%PDF-")


def test_run_flow_omits_pdf_by_default(tmp_path):
    url = _write_page(tmp_path)
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        f"""
        [screenwright]
        base_url = ""

        [[flows]]
        name = "no-pdf"

          [[flows.steps]]
          action = "navigate"
          url = "{url}"

          [[flows.steps]]
          action = "capture"
          name = "shot"
        """
    )
    cfg = load_config(toml_path)
    flow = cfg.get_flow("no-pdf")
    output_root = tmp_path / "output"

    import asyncio

    result = asyncio.run(run_flow(flow, cfg, output_root))

    assert result.captures[0].pdf_path is None
    assert not (output_root / "no-pdf" / "shot.pdf").exists()


def test_run_flow_capture_variants_produce_suffixed_files_only(tmp_path):
    url = _write_page(tmp_path)
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        f"""
        [screenwright]
        base_url = ""

        [[flows]]
        name = "variants"

          [[flows.steps]]
          action = "navigate"
          url = "{url}"

          [[flows.steps]]
          action = "capture"
          name = "shot"

            [[flows.steps.variants]]
            name = "mobile"
            viewport_width = 390
            viewport_height = 844

            [[flows.steps.variants]]
            name = "desktop"
            viewport_width = 1280
            viewport_height = 720
        """
    )
    cfg = load_config(toml_path)
    flow = cfg.get_flow("variants")
    output_root = tmp_path / "output"

    import asyncio

    result = asyncio.run(run_flow(flow, cfg, output_root))

    assert result.error is None
    names = [c.capture_name for c in result.captures]
    assert names == ["shot-mobile", "shot-desktop"]

    mobile_width, _ = _png_dimensions(output_root / "variants" / "shot-mobile.png")
    desktop_width, _ = _png_dimensions(output_root / "variants" / "shot-desktop.png")
    assert mobile_width == 390
    assert desktop_width == 1280

    # Variants replace the single capture entirely — no unsuffixed "shot.png".
    assert not (output_root / "variants" / "shot.png").exists()


def test_run_flow_restores_viewport_after_variants_step(tmp_path):
    url = _write_page(tmp_path)
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        f"""
        [screenwright]
        base_url = ""

        [[flows]]
        name = "restore-viewport"

          [[flows.steps]]
          action = "navigate"
          url = "{url}"

          [[flows.steps]]
          action = "capture"
          name = "first"

            [[flows.steps.variants]]
            name = "mobile"
            viewport_width = 390
            viewport_height = 844

          [[flows.steps]]
          action = "capture"
          name = "second"
        """
    )
    cfg = load_config(toml_path)
    flow = cfg.get_flow("restore-viewport")
    output_root = tmp_path / "output"

    import asyncio

    result = asyncio.run(run_flow(flow, cfg, output_root))

    assert result.error is None
    # "second" has no variants — it must run at the flow's own default
    # viewport (1280), not be left at "first" variant's mobile width.
    second = next(c for c in result.captures if c.capture_name == "second")
    width, _ = _png_dimensions(second.path)
    assert width == 1280


def test_run_flow_variants_compose_with_accessibility_snapshot_and_pdf(tmp_path):
    url = _write_page(tmp_path)
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        f"""
        [screenwright]
        base_url = ""

        [[flows]]
        name = "variants-with-extras"

          [[flows.steps]]
          action = "navigate"
          url = "{url}"

          [[flows.steps]]
          action = "capture"
          name = "shot"
          accessibility_snapshot = true
          pdf = true

            [[flows.steps.variants]]
            name = "mobile"
            viewport_width = 390
            viewport_height = 844
        """
    )
    cfg = load_config(toml_path)
    flow = cfg.get_flow("variants-with-extras")
    output_root = tmp_path / "output"

    import asyncio

    result = asyncio.run(run_flow(flow, cfg, output_root))

    assert result.error is None
    capture = result.captures[0]
    assert capture.capture_name == "shot-mobile"
    assert (
        capture.accessibility_path == output_root / "variants-with-extras" / "shot-mobile.aria.yaml"
    )
    assert capture.accessibility_path.exists()
    assert capture.pdf_path == output_root / "variants-with-extras" / "shot-mobile.pdf"
    assert capture.pdf_path.exists()


def test_run_flow_capture_step_without_variants_behaves_exactly_as_before(tmp_path):
    # Zero variants is the default — confirms no behavior change for every
    # flow written before this feature existed.
    url = _write_page(tmp_path)
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        f"""
        [screenwright]
        base_url = ""

        [[flows]]
        name = "no-variants"

          [[flows.steps]]
          action = "navigate"
          url = "{url}"

          [[flows.steps]]
          action = "capture"
          name = "shot"
        """
    )
    cfg = load_config(toml_path)
    flow = cfg.get_flow("no-variants")
    output_root = tmp_path / "output"

    import asyncio

    result = asyncio.run(run_flow(flow, cfg, output_root))

    assert result.error is None
    assert len(result.captures) == 1
    assert result.captures[0].capture_name == "shot"
    assert result.captures[0].path == output_root / "no-variants" / "shot.png"


def test_run_flow_masks_selector_without_error(tmp_path):
    url = _write_page(tmp_path)
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        f"""
        [screenwright]
        base_url = ""

        [[flows]]
        name = "masked"

          [[flows.steps]]
          action = "navigate"
          url = "{url}"

          [[flows.steps]]
          action = "capture"
          name = "shot"
          mask = ["#remember-me"]
          mask_color = "#000000"
        """
    )
    cfg = load_config(toml_path)
    flow = cfg.get_flow("masked")
    output_root = tmp_path / "output"

    import asyncio

    result = asyncio.run(run_flow(flow, cfg, output_root))

    assert result.error is None
    assert result.captures[0].path.exists()


def test_run_flow_mask_of_nonexistent_selector_is_a_silent_no_op(tmp_path):
    # Unlike the `selector` param (which raises "Selector not found" if
    # missing), Playwright's mask locators silently match nothing rather
    # than erroring — verified directly against the installed Playwright
    # before writing this. A flow shouldn't fail just because an optional
    # masking target isn't present on every page it's used on.
    url = _write_page(tmp_path)
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        f"""
        [screenwright]
        base_url = ""

        [[flows]]
        name = "mask-missing"

          [[flows.steps]]
          action = "navigate"
          url = "{url}"

          [[flows.steps]]
          action = "capture"
          name = "shot"
          mask = ["#does-not-exist-anywhere"]
        """
    )
    cfg = load_config(toml_path)
    flow = cfg.get_flow("mask-missing")
    output_root = tmp_path / "output"

    import asyncio

    result = asyncio.run(run_flow(flow, cfg, output_root))

    assert result.error is None
    assert result.captures[0].path.exists()


def test_run_flow_animations_allow_does_not_error(tmp_path):
    url = _write_page(tmp_path)
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        f"""
        [screenwright]
        base_url = ""

        [[flows]]
        name = "allow-animations"

          [[flows.steps]]
          action = "navigate"
          url = "{url}"

          [[flows.steps]]
          action = "capture"
          name = "shot"
          animations = "allow"
        """
    )
    cfg = load_config(toml_path)
    flow = cfg.get_flow("allow-animations")
    output_root = tmp_path / "output"

    import asyncio

    result = asyncio.run(run_flow(flow, cfg, output_root))

    assert result.error is None
    assert result.captures[0].path.exists()


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
