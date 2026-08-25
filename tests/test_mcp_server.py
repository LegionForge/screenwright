from __future__ import annotations

from pathlib import Path

import pytest

from screenwright.config import ScreenwrightConfig
from screenwright.mcp_server import (
    _DEFAULT_OUTPUT,
    _resolve_capture_path,
    _resolve_config,
    _resolve_output,
    capture_element,
    capture_url,
    describe_flow,
    describe_screenshot,
    list_flows,
    run_flow_tool,
)

_HTML = """
<!doctype html>
<html><head><title>Test</title></head>
<body><h1>Hello</h1><div id="content">content</div></body></html>
"""


def _write_page(tmp_path):
    page = tmp_path / "page.html"
    page.write_text(_HTML)
    return f"file://{page}"


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


def test_run_flow_tool_vision_describe_writes_metadata_sidecars(tmp_path, monkeypatch):
    import json

    from screenwright.vision import ScreenshotMetadata

    def fake_describe(image_path, cfg):
        return ScreenshotMetadata(description="A login form")

    monkeypatch.setattr("screenwright.vision.describe", fake_describe)

    html = tmp_path / "page.html"
    html.write_text("<!doctype html><html><body><h1>hi</h1></body></html>")
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

    import asyncio

    output = asyncio.run(
        run_flow_tool(
            "demo",
            config_path=str(toml_path),
            output_dir=str(output_dir),
            vision_describe=True,
        )
    )

    assert output["error"] is None
    sidecar = output_dir / "demo" / "shot.json"
    assert sidecar.exists()
    assert json.loads(sidecar.read_text())["description"] == "A login form"
    # write_flow_output also (re)writes index.md, matching cli.py's own
    # capture-then-describe-then-write ordering.
    assert (output_dir / "demo" / "index.md").exists()


def test_run_flow_tool_reports_write_flow_output_failure_instead_of_raising(tmp_path, monkeypatch):
    from screenwright.vision import ScreenshotMetadata

    def fake_describe(image_path, cfg):
        return ScreenshotMetadata(description="A login form")

    def broken_write_flow_output(_result, _output_root):
        raise OSError("simulated disk error writing flow output")

    monkeypatch.setattr("screenwright.vision.describe", fake_describe)
    monkeypatch.setattr("screenwright.output.write_flow_output", broken_write_flow_output)

    html = tmp_path / "page.html"
    html.write_text("<!doctype html><html><body><h1>hi</h1></body></html>")
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

    import asyncio

    output = asyncio.run(
        run_flow_tool(
            "demo",
            config_path=str(toml_path),
            output_dir=str(output_dir),
            vision_describe=True,
        )
    )

    # A failure writing output must not raise out of this call — the
    # already-captured screenshot is still reported, and the write
    # failure surfaces via the error field, same as any other
    # step/setup/finalize failure.
    assert len(output["captures"]) == 1
    assert output["error"] is not None
    assert "Failed to write flow output" in output["error"]
    assert "simulated disk error" in output["error"]
    assert Path(output["captures"][0]).exists()


def test_run_flow_tool_defaults_to_no_vision_describe(tmp_path):
    html = tmp_path / "page.html"
    html.write_text("<!doctype html><html><body><h1>hi</h1></body></html>")
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

    import asyncio

    output = asyncio.run(
        run_flow_tool("demo", config_path=str(toml_path), output_dir=str(output_dir))
    )

    assert output["error"] is None
    assert len(output["captures"]) == 1
    # No vision_describe=True passed — no sidecar, and no index.md/JSON
    # written at all, matching this call's behavior before this option
    # existed.
    assert not (output_dir / "demo" / "shot.json").exists()
    assert not (output_dir / "demo" / "index.md").exists()


def test_run_flow_tool_vision_describe_continues_past_single_failure(tmp_path, monkeypatch):
    import json

    from screenwright.vision import ScreenshotMetadata

    calls = {"count": 0}

    def flaky_describe(image_path, cfg):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("simulated vision API outage")
        return ScreenshotMetadata(description="second capture described fine")

    monkeypatch.setattr("screenwright.vision.describe", flaky_describe)

    html = tmp_path / "page.html"
    html.write_text("<!doctype html><html><body><h1>hi</h1></body></html>")
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
          name = "first"

          [[flows.steps]]
          action = "capture"
          name = "second"
        """
    )
    output_dir = tmp_path / "out"

    import asyncio

    output = asyncio.run(
        run_flow_tool(
            "demo",
            config_path=str(toml_path),
            output_dir=str(output_dir),
            vision_describe=True,
        )
    )

    assert output["error"] is None
    assert len(output["captures"]) == 2
    assert not (output_dir / "demo" / "first.json").exists()
    second_sidecar = output_dir / "demo" / "second.json"
    assert second_sidecar.exists()
    assert json.loads(second_sidecar.read_text())["description"] == "second capture described fine"


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


def test_describe_screenshot_rejects_unknown_provider(tmp_path):
    # provider is typed as Literal["anthropic", "ollama", "openai"] so a real
    # MCP client sees the valid options in the tool's schema; this guards
    # the runtime fallback for an out-of-schema value (a client that
    # ignores the schema, or a stale client) still gets a clear rejection
    # from VisionConfig rather than an unrelated error deeper in describe().
    import asyncio

    from pydantic import ValidationError

    png = tmp_path / "shot.png"
    png.write_bytes(b"fake-png")

    with pytest.raises(ValidationError):
        asyncio.run(describe_screenshot(str(png), provider="bogus"))


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


def test_describe_screenshot_threads_custom_prompt_into_vision_config(tmp_path, monkeypatch):
    import asyncio

    from screenwright.vision import ScreenshotMetadata

    png = tmp_path / "shot.png"
    png.write_bytes(b"fake-png")

    captured_prompts = []

    def fake_describe(image_path, cfg):
        captured_prompts.append(cfg.prompt)
        return ScreenshotMetadata(description="ok")

    monkeypatch.setattr("screenwright.vision.describe", fake_describe)

    asyncio.run(
        describe_screenshot(
            str(png), structured_metadata=False, prompt="Focus on accessibility issues"
        )
    )

    assert captured_prompts == ["Focus on accessibility issues"]


def test_describe_screenshot_uses_default_prompt_when_not_given(tmp_path, monkeypatch):
    import asyncio

    from screenwright.config import VisionConfig
    from screenwright.vision import ScreenshotMetadata

    png = tmp_path / "shot.png"
    png.write_bytes(b"fake-png")

    captured_prompts = []

    def fake_describe(image_path, cfg):
        captured_prompts.append(cfg.prompt)
        return ScreenshotMetadata(description="ok")

    monkeypatch.setattr("screenwright.vision.describe", fake_describe)

    asyncio.run(describe_screenshot(str(png), structured_metadata=False))

    assert captured_prompts == [VisionConfig().prompt]


@pytest.mark.integration
def _png_dimensions(path):
    # PNG signature (8 bytes) + IHDR chunk length/type (8 bytes), then
    # width/height as big-endian uint32 — avoids adding an image-library
    # dependency just to assert a screenshot's viewport size in tests.
    data = path.read_bytes()
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    return width, height


def test_capture_url_full_page(tmp_path):
    import asyncio

    url = _write_page(tmp_path)
    out_dir = tmp_path / "out"

    saved = asyncio.run(capture_url(url, "homepage", output_dir=str(out_dir)))

    assert Path(saved) == out_dir / "homepage.png"
    assert Path(saved).exists()
    assert Path(saved).stat().st_size > 0


def test_capture_url_respects_custom_viewport(tmp_path):
    # capture_single_url has long supported timeout_ms/viewport_width/
    # viewport_height/animations, but capture_url never wired them through
    # — always used capture_single_url's hardcoded defaults regardless of
    # what an agent asked for. This proves the wiring, not just that the
    # param exists: a real behavioral difference in the output.
    import asyncio

    url = _write_page(tmp_path)
    out_dir = tmp_path / "out"

    saved = asyncio.run(
        capture_url(
            url,
            "mobile",
            output_dir=str(out_dir),
            viewport_width=390,
            viewport_height=844,
        )
    )

    width, height = _png_dimensions(Path(saved))
    assert width == 390
    assert height == 844


def test_capture_element_accepts_new_capture_params(tmp_path):
    # Same wiring as capture_url, for capture_element. An element-scoped
    # screenshot's own pixel dimensions don't move with viewport_width the
    # way a full-page capture's do, so this can't prove a visible pixel
    # difference the way test_capture_url_respects_custom_viewport does —
    # it still catches a wiring typo (a mismatched kwarg name would raise
    # a TypeError here), since this calls the identical capture_single_url
    # wiring capture_url's own test already proves takes effect.
    import asyncio

    url = _write_page(tmp_path)
    out_dir = tmp_path / "out"

    saved = asyncio.run(
        capture_element(
            url,
            "#content",
            "content-shot",
            output_dir=str(out_dir),
            wait_until="domcontentloaded",
            timeout_ms=15000,
            viewport_width=600,
            viewport_height=400,
            animations="allow",
        )
    )

    assert Path(saved).exists()
    assert Path(saved).stat().st_size > 0


@pytest.mark.integration
def test_capture_url_rejects_path_traversal_name(tmp_path):
    import asyncio

    url = _write_page(tmp_path)
    out_dir = tmp_path / "out"

    with pytest.raises(ValueError):
        asyncio.run(capture_url(url, "../escape", output_dir=str(out_dir)))


@pytest.mark.integration
def test_capture_element(tmp_path):
    import asyncio

    url = _write_page(tmp_path)
    out_dir = tmp_path / "out"

    saved = asyncio.run(capture_element(url, "#content", "content-shot", output_dir=str(out_dir)))

    assert Path(saved) == out_dir / "content-shot.png"
    assert Path(saved).exists()


def test_list_flows_returns_flow_names_from_config(tmp_path):
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        """
        [[flows]]
        name = "homepage"
        [[flows]]
        name = "login"
        """
    )

    import asyncio

    result = asyncio.run(list_flows(config_path=str(toml_path)))

    assert result == ["homepage", "login"]


def test_list_flows_returns_empty_list_when_no_config_available(monkeypatch):
    monkeypatch.delenv("SCREENWRIGHT_CONFIG", raising=False)

    import asyncio

    result = asyncio.run(list_flows(config_path=None))

    assert result == []


def test_resolve_config_uses_explicit_path_over_env_var(tmp_path, monkeypatch):
    explicit = tmp_path / "explicit.toml"
    explicit.write_text('[[flows]]\nname = "from-explicit"\n')
    env_config = tmp_path / "env.toml"
    env_config.write_text('[[flows]]\nname = "from-env"\n')
    monkeypatch.setenv("SCREENWRIGHT_CONFIG", str(env_config))

    cfg = _resolve_config(str(explicit))

    assert cfg.flow_names() == ["from-explicit"]


def test_resolve_config_falls_back_to_env_var_when_no_explicit_path(tmp_path, monkeypatch):
    env_config = tmp_path / "env.toml"
    env_config.write_text('[[flows]]\nname = "from-env"\n')
    monkeypatch.setenv("SCREENWRIGHT_CONFIG", str(env_config))

    cfg = _resolve_config(None)

    assert cfg.flow_names() == ["from-env"]


def test_resolve_config_returns_empty_default_when_nothing_set(monkeypatch):
    monkeypatch.delenv("SCREENWRIGHT_CONFIG", raising=False)

    cfg = _resolve_config(None)

    assert cfg.flows == []


def test_run_flow_tool_raises_clear_error_for_unknown_flow_name(tmp_path):
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        """
        [[flows]]
        name = "homepage"
        [[flows]]
        name = "login"
        """
    )

    import asyncio

    with pytest.raises(ValueError, match="not found") as exc_info:
        asyncio.run(run_flow_tool("does-not-exist", config_path=str(toml_path)))

    # The error should list what IS available, so an agent can self-correct
    # on the next call instead of guessing.
    assert "homepage" in str(exc_info.value)
    assert "login" in str(exc_info.value)


def test_describe_flow_returns_empty_when_flow_never_run(tmp_path):
    import asyncio

    result = asyncio.run(describe_flow("never-run", output_dir=str(tmp_path / "out")))

    assert result == {"flow_name": "never-run", "index_md": None, "captures": []}


@pytest.mark.parametrize(
    "malicious_flow_name",
    [
        "../../../../etc/passwd",
        "..",
        "foo/../../bar",
        "/etc/passwd",
        "a/b",
    ],
)
def test_describe_flow_rejects_path_traversal_flow_name(tmp_path, malicious_flow_name):
    # flow_name builds `out_root / flow_name` directly — without
    # validation, a value like "../../secrets" would let describe_flow read
    # index.md/*.png/*.json from arbitrary directories outside out_root and
    # return their contents to the calling agent. Same threat model as
    # capture_url/capture_element's `name` param: flow_name can come from
    # an LLM acting on untrusted page content.
    import asyncio

    with pytest.raises(ValueError):
        asyncio.run(describe_flow(malicious_flow_name, output_dir=str(tmp_path / "out")))


def test_describe_flow_bundles_index_and_capture_metadata(tmp_path):
    import json

    flow_dir = tmp_path / "out" / "homepage"
    flow_dir.mkdir(parents=True)
    (flow_dir / "index.md").write_text("# homepage\n\n| Screenshot | Description |\n")

    (flow_dir / "hero.png").write_bytes(b"fake-png")
    (flow_dir / "hero.json").write_text(json.dumps({"description": "Hero section"}))

    # A capture with no metadata sidecar — vision disabled, or describe()
    # failed for just this one — must appear with metadata: None, not be
    # silently dropped from the bundle.
    (flow_dir / "footer.png").write_bytes(b"fake-png")

    import asyncio

    result = asyncio.run(describe_flow("homepage", output_dir=str(tmp_path / "out")))

    assert result["flow_name"] == "homepage"
    assert "# homepage" in result["index_md"]
    captures_by_name = {c["name"]: c for c in result["captures"]}
    assert captures_by_name["hero"]["metadata"] == {"description": "Hero section"}
    assert captures_by_name["footer"]["metadata"] is None
    assert captures_by_name["hero"]["path"] == str(flow_dir / "hero.png")


def test_mcp_instructions_reference_real_tool_names():
    # `mcp.instructions` is sent verbatim to every connecting MCP client as
    # guidance on how to use this server — a tool name mentioned there that
    # doesn't match a real registered tool (e.g. "run_flow" when the actual
    # tool is "run_flow_tool") silently misleads every agent that reads it.
    # Guards exactly that class of bug: every real tool name must appear,
    # by its exact name, somewhere in the instructions text.
    import asyncio
    import re

    from screenwright.mcp_server import mcp

    tools = asyncio.run(mcp.list_tools())
    real_names = {t.name for t in tools}
    assert real_names, "expected at least one registered tool"

    for name in real_names:
        assert re.search(rf"\b{re.escape(name)}\b", mcp.instructions), (
            f"tool {name!r} is registered but never mentioned by its exact name in mcp.instructions"
        )
