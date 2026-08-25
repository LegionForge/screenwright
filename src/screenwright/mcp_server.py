from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Literal, Optional

from mcp.server.fastmcp import FastMCP

from screenwright.capture import FlowResult, capture_single_url, run_flow
from screenwright.config import ScreenwrightConfig, load_config, validate_safe_name

mcp = FastMCP(
    "screenwright",
    instructions=(
        "Screenwright captures UI screenshots for documentation. "
        "Use capture_url or capture_element for one-off captures. "
        "Use list_flows to see what flows a TOML config defines. "
        "Use run_flow_tool to execute a multi-step flow from a TOML config — pass "
        "vision_describe=true to also describe each capture and write .json metadata "
        "sidecars in the same call, instead of a separate describe_screenshot round-trip "
        "per screenshot. "
        "Use describe_screenshot to get a vision-model description of any captured PNG. "
        "Use describe_flow to get everything already captured for a flow (markdown index "
        "plus every capture's structured metadata) in one call after run_flow_tool."
    ),
)

_DEFAULT_OUTPUT = Path(tempfile.gettempdir()) / "screenwright-output"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _looks_like_png(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(len(_PNG_MAGIC)) == _PNG_MAGIC
    except OSError:
        return False


def _ensure_private_default_output_dir(path: Path) -> None:
    """Create/lock down `_DEFAULT_OUTPUT` (only) with owner-only (0700) permissions.

    `_DEFAULT_OUTPUT` lives in the system temp directory (e.g.
    `/tmp/screenwright-output`) — a fixed, predictable path any local user
    can see. Left at the default `mkdir()` permissions, captures written
    there (potentially showing sensitive UI: admin panels, unmasked internal
    dashboards) are readable by every other local user on a shared machine,
    and a symlink pre-planted at that exact path could redirect writes
    somewhere the caller never intended. Only ever called for
    `_DEFAULT_OUTPUT` itself — an explicit `output_dir` the caller chose
    (e.g. `docs/screenshots`, meant to be committed and shared) is left
    alone, since forcing its permissions could break that deliberate use.
    """
    if path.is_symlink():
        raise RuntimeError(
            f"Refusing to write through {path}: it's a symlink, not a real directory. "
            "This is the shared default output directory in the system temp dir — a "
            "symlink there could be a pre-planted attack redirecting captures "
            "somewhere unintended. Pass an explicit output_dir instead."
        )
    path.mkdir(mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)


def _resolve_config(config_path: Optional[str]) -> ScreenwrightConfig:
    path = config_path or os.environ.get("SCREENWRIGHT_CONFIG")
    if path:
        return load_config(path)
    return ScreenwrightConfig()


def _resolve_output(config: ScreenwrightConfig, override: Optional[str]) -> Path:
    """Pick the output directory: explicit override > config's own value > temp default.

    A user who deliberately sets `output_dir = "docs/screenshots"` (the
    same string as the field default) must still get that directory, not
    get silently redirected to a temp dir. Comparing the *value* against
    the default string can't distinguish "explicitly set to the default"
    from "never set" — check `model_fields_set` instead, which pydantic
    populates from whatever keys were actually present in the parsed TOML.
    """
    if override:
        return Path(override)
    if "output_dir" in config.model_fields_set:
        return Path(config.output_dir)
    return _DEFAULT_OUTPUT


def _resolve_capture_path(out_root: Path, name: str) -> Path:
    """Validate `name` and confirm the resulting PNG path stays inside out_root.

    `name` on this MCP surface can be supplied by an LLM that just read
    untrusted page content, so this is a real containment boundary, not a
    formality — validate_safe_name blocks path separators/traversal
    segments, and the is_relative_to check catches anything that slips
    through (e.g. a platform-specific separator the regex didn't account for).
    """
    validate_safe_name(name)
    out_root = out_root.resolve()
    out_path = (out_root / f"{name}.png").resolve()
    if not out_path.is_relative_to(out_root):
        raise ValueError(f"Resolved capture path {out_path} escapes output_dir {out_root}")
    return out_path


@mcp.tool()
async def capture_url(
    url: str,
    name: str,
    selector: Optional[str] = None,
    output_dir: Optional[str] = None,
    wait_until: Literal["load", "domcontentloaded", "networkidle", "commit"] = "load",
    timeout_ms: int = 30000,
    viewport_width: int = 1280,
    viewport_height: int = 720,
    animations: Literal["disabled", "allow"] = "disabled",
    mask: Optional[list[str]] = None,
    mask_color: Optional[str] = None,
) -> str:
    """
    Navigate to a URL and capture a screenshot.

    Args:
        url: Full URL to navigate to.
        name: Filename stem for the PNG (no extension needed).
        selector: Optional CSS selector — captures only that element instead of full page.
        output_dir: Where to save the PNG. Defaults to a temp directory.
        wait_until: Playwright navigation wait condition. Default 'load'. Use
            'networkidle' cautiously — a page with a persistent websocket/SSE
            connection (live dashboards, log viewers, chat UIs) never goes
            network-idle and will hang until timeout_ms.
        timeout_ms: Navigation timeout in milliseconds. Default 30000 — raise this for a
            slow-loading page instead of retrying the call.
        viewport_width: Default 1280 — e.g. 390 for a mobile-sized capture.
        viewport_height: Default 720.
        animations: 'disabled' (default) freezes CSS animations/transitions for a
            deterministic screenshot; 'allow' captures whatever frame is mid-animation.
        mask: CSS selectors to fill with a solid color before capturing — e.g. a live
            clock or an avatar — so repeated captures of the same page produce the same
            pixels. A selector matching nothing is a silent no-op, not an error.
        mask_color: Override color for masked elements. Playwright's own default is pink
            (#FF00FF), chosen to be unmissable.

    Returns:
        Absolute path to the saved PNG file.
    """
    out_root = Path(output_dir) if output_dir else _DEFAULT_OUTPUT
    if out_root == _DEFAULT_OUTPUT:
        _ensure_private_default_output_dir(out_root)
    else:
        out_root.mkdir(parents=True, exist_ok=True)
    out_path = _resolve_capture_path(out_root, name)

    saved = await capture_single_url(
        url,
        out_path,
        selector,
        wait_until=wait_until,
        timeout_ms=timeout_ms,
        viewport_width=viewport_width,
        viewport_height=viewport_height,
        animations=animations,
        mask=mask,
        mask_color=mask_color,
    )
    return str(saved)


@mcp.tool()
async def capture_element(
    url: str,
    selector: str,
    name: str,
    output_dir: Optional[str] = None,
    wait_until: Literal["load", "domcontentloaded", "networkidle", "commit"] = "load",
    timeout_ms: int = 30000,
    viewport_width: int = 1280,
    viewport_height: int = 720,
    animations: Literal["disabled", "allow"] = "disabled",
    mask: Optional[list[str]] = None,
    mask_color: Optional[str] = None,
) -> str:
    """
    Navigate to a URL and capture a specific DOM element.

    Args:
        url: Full URL to navigate to.
        selector: CSS selector for the element to capture.
        name: Filename stem for the PNG.
        output_dir: Where to save the PNG.
        wait_until: Playwright navigation wait condition. Default 'load'. Use
            'networkidle' cautiously — a page with a persistent websocket/SSE
            connection never goes network-idle and will hang until timeout_ms.
        timeout_ms: Navigation timeout in milliseconds. Default 30000.
        viewport_width: Default 1280 — e.g. 390 for a mobile-sized capture.
        viewport_height: Default 720.
        animations: 'disabled' (default) freezes CSS animations/transitions for a
            deterministic screenshot; 'allow' captures whatever frame is mid-animation.
        mask: CSS selectors to fill with a solid color before capturing — e.g. a live
            clock or an avatar — so repeated captures of the same page produce the same
            pixels. A selector matching nothing is a silent no-op, not an error.
        mask_color: Override color for masked elements. Playwright's own default is pink
            (#FF00FF), chosen to be unmissable.

    Returns:
        Absolute path to the saved PNG file.
    """
    out_root = Path(output_dir) if output_dir else _DEFAULT_OUTPUT
    if out_root == _DEFAULT_OUTPUT:
        _ensure_private_default_output_dir(out_root)
    else:
        out_root.mkdir(parents=True, exist_ok=True)
    out_path = _resolve_capture_path(out_root, name)

    saved = await capture_single_url(
        url,
        out_path,
        selector,
        wait_until=wait_until,
        timeout_ms=timeout_ms,
        viewport_width=viewport_width,
        viewport_height=viewport_height,
        animations=animations,
        mask=mask,
        mask_color=mask_color,
    )
    return str(saved)


@mcp.tool()
async def run_flow_tool(
    flow_name: str,
    config_path: Optional[str] = None,
    output_dir: Optional[str] = None,
    vision_describe: bool = False,
) -> dict:
    """
    Execute a named flow from a TOML config file.

    Args:
        flow_name: Name of the flow to run (must exist in the config).
        config_path: Path to TOML config. Falls back to SCREENWRIGHT_CONFIG env var.
        output_dir: Override the output directory from the config.
        vision_describe: When true, run the config's vision provider on each capture
            after the flow completes and write `{name}.json` metadata sidecars — the
            same auto-describe step `cli.py`'s `run` command performs, now available
            here too. Without this, nothing on the MCP surface ever writes a sidecar,
            so `describe_flow` afterward has no metadata to bundle unless you call
            `describe_screenshot` yourself for every capture path. A per-capture
            describe() failure doesn't abort the others or fail this call — that
            capture's sidecar is simply not written, matching `output.py`'s existing
            "metadata is optional" handling. Defaults to false since this call is
            otherwise fast and free of vision-API cost.

    Returns:
        A dict: {"captures": [absolute PNG paths], "video_path": str | None,
        "video_mp4_path": str | None, "error": str | None,
        "failed_step_index": int | None}. If a step fails mid-flow, `captures`
        still contains everything captured before the failure — this call
        does not raise for a mid-flow step failure, only for a missing flow
        name or a config error, so a partial result is always visible rather
        than lost behind an exception.
    """
    cfg = _resolve_config(config_path)
    flow_def = cfg.get_flow(flow_name)
    if flow_def is None:
        available = ", ".join(cfg.flow_names()) or "(none)"
        raise ValueError(f"Flow {flow_name!r} not found. Available: {available}")

    out_root = _resolve_output(cfg, output_dir)
    if out_root == _DEFAULT_OUTPUT:
        _ensure_private_default_output_dir(out_root)
    result: FlowResult = await run_flow(flow_def, cfg, out_root)

    if vision_describe and result.captures:
        from screenwright.output import write_flow_output
        from screenwright.vision import describe

        for capture in result.captures:
            try:
                capture.metadata = await asyncio.to_thread(describe, capture.path, cfg.vision)
            except Exception:
                pass  # leave metadata unset; output.py/describe_flow already tolerate None
        try:
            write_flow_output(result, out_root)
        except Exception as exc:
            # A failure writing index.md/.json sidecars (disk full,
            # permission denied) must not crash this tool call and lose
            # every already-captured screenshot behind an unhandled
            # exception — report it the same way run_flow itself already
            # reports a step/setup/finalize failure via result.error.
            write_error = f"Failed to write flow output: {exc}"
            result.error = f"{result.error}; {write_error}" if result.error else write_error

    return {
        "captures": [str(c.path) for c in result.captures],
        "video_path": str(result.video_path) if result.video_path else None,
        "video_mp4_path": str(result.video_mp4_path) if result.video_mp4_path else None,
        "error": result.error,
        "failed_step_index": result.failed_step_index,
    }


@mcp.tool()
async def list_flows(config_path: Optional[str] = None) -> list[str]:
    """
    List the names of all flows defined in the loaded config.

    Args:
        config_path: Path to TOML config. Falls back to SCREENWRIGHT_CONFIG env var.

    Returns:
        List of flow names.
    """
    cfg = _resolve_config(config_path)
    return cfg.flow_names()


@mcp.tool()
async def describe_flow(
    flow_name: str,
    config_path: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> dict:
    """
    Return everything already captured for a flow — the markdown index and every
    capture's structured metadata — in one call, instead of one describe_screenshot
    round-trip per screenshot.

    This reads existing output on disk; it does not run the flow. Call
    run_flow_tool first.

    Args:
        flow_name: Name of a flow that has already been run.
        config_path: Path to TOML config, used only to resolve the output
            directory the same way run_flow_tool does. Falls back to
            SCREENWRIGHT_CONFIG.
        output_dir: Override the output directory from the config.

    Returns:
        {"flow_name": str, "index_md": str | None, "captures": [
            {"name": str, "path": str, "metadata": dict | None}, ...
        ]}. index_md and captures are empty/None if the flow's output
        directory doesn't exist yet (it hasn't been run). A capture with no
        .json sidecar has metadata: None rather than being omitted — the
        common case being run_flow_tool was called without
        vision_describe=true (its default), but also covers describe()
        failing for just that one capture.
    """
    # flow_name builds a filesystem path below (out_root / flow_name) and,
    # like capture_url/capture_element's `name` param, can come from an LLM
    # acting on untrusted page content — without this, "../../etc" style
    # values would let describe_flow read index.md/*.png/*.json from
    # arbitrary directories outside out_root and return their contents to
    # the calling agent.
    validate_safe_name(flow_name)
    cfg = _resolve_config(config_path)
    out_root = _resolve_output(cfg, output_dir)
    flow_dir = out_root / flow_name

    if not flow_dir.is_dir():
        return {"flow_name": flow_name, "index_md": None, "captures": []}

    index_path = flow_dir / "index.md"
    index_md = index_path.read_text(encoding="utf-8") if index_path.exists() else None

    captures = []
    for png_path in sorted(flow_dir.glob("*.png")):
        json_path = png_path.with_suffix(".json")
        metadata = json.loads(json_path.read_text(encoding="utf-8")) if json_path.exists() else None
        captures.append({"name": png_path.stem, "path": str(png_path), "metadata": metadata})

    return {"flow_name": flow_name, "index_md": index_md, "captures": captures}


@mcp.tool()
async def describe_screenshot(
    screenshot_path: str,
    provider: Literal["anthropic", "ollama", "openai"] = "anthropic",
    model: str = "claude-haiku-4-5",
    structured_metadata: bool = True,
    prompt: Optional[str] = None,
) -> str:
    """
    Send a captured screenshot to a vision model and return a description (or JSON metadata).

    Args:
        screenshot_path: Absolute path to the PNG file.
        provider: 'anthropic' (requires ANTHROPIC_API_KEY), 'openai' (requires OPENAI_API_KEY),
                  or 'ollama' (local, no key needed).
        model: Model name. For anthropic: 'claude-haiku-4-5'. For openai: 'gpt-4o-mini'.
               For ollama: 'moondream', 'llava'.
        structured_metadata: When true, returns a JSON string with description, components,
                              state, title, errors_visible, and accessibility_notes fields.
        prompt: Custom instruction for the vision model — e.g. "Focus on accessibility
                issues" or "Describe in Spanish". Defaults to Screenwright's built-in
                generic description prompt. When structured_metadata=true, the JSON-
                structure instruction is still appended after this prompt, same as a
                TOML-configured `[vision] prompt`.

    Returns:
        Description string, or JSON string when structured_metadata is true.

    Raises:
        FileNotFoundError: screenshot_path doesn't exist.
        ValueError: the file at screenshot_path isn't a PNG (checked by magic bytes, not
            extension). screenshot_path can come from an LLM acting on untrusted page
            content, and this tool base64-encodes the whole file and forwards it to a
            third-party vision API — without this check, an agent could be tricked (e.g. via
            a prompt-injection payload on a captured page) into reading and exfiltrating an
            arbitrary local file (a `.env`, an SSH key) through this tool.
    """
    from screenwright.config import VisionConfig
    from screenwright.vision import describe

    path = Path(screenshot_path)
    if not path.exists():
        raise FileNotFoundError(f"Screenshot not found: {screenshot_path}")
    if not _looks_like_png(path):
        raise ValueError(
            f"{screenshot_path} is not a PNG file (bad magic bytes). describe_screenshot only "
            "accepts PNGs — refusing to read and forward arbitrary file contents to a vision "
            "provider."
        )

    vision_cfg_kwargs = {
        "provider": provider,
        "model": model,
        "structured_metadata": structured_metadata,
    }
    if prompt is not None:
        vision_cfg_kwargs["prompt"] = prompt
    vision_cfg = VisionConfig(**vision_cfg_kwargs)

    metadata = await asyncio.to_thread(describe, path, vision_cfg)

    if structured_metadata:
        return json.dumps(metadata.model_dump(), indent=2)
    return metadata.description


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
