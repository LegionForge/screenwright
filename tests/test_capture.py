from __future__ import annotations

import pytest

from screenwright.capture import capture_single_url, run_flow
from screenwright.config import load_config

pytestmark = pytest.mark.integration

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
