from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

from screenwright.capture import FlowResult, capture_single_url, run_flow
from screenwright.config import ScreenwrightConfig, load_config, validate_safe_name

mcp = FastMCP(
    "screenwright",
    instructions=(
        "Screenwright captures UI screenshots for documentation. "
        "Use capture_url or capture_element for one-off captures. "
        "Use run_flow to execute a multi-step flow from a TOML config. "
        "Use describe_screenshot to get a vision-model description of any captured PNG."
    ),
)

_DEFAULT_OUTPUT = Path(tempfile.gettempdir()) / "screenwright-output"


def _resolve_config(config_path: Optional[str]) -> ScreenwrightConfig:
    path = config_path or os.environ.get("SCREENWRIGHT_CONFIG")
    if path:
        return load_config(path)
    return ScreenwrightConfig()


def _resolve_output(config: ScreenwrightConfig, override: Optional[str]) -> Path:
    if override:
        return Path(override)
    if config.output_dir and config.output_dir != "docs/screenshots":
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
) -> str:
    """
    Navigate to a URL and capture a screenshot.

    Args:
        url: Full URL to navigate to.
        name: Filename stem for the PNG (no extension needed).
        selector: Optional CSS selector — captures only that element instead of full page.
        output_dir: Where to save the PNG. Defaults to a temp directory.

    Returns:
        Absolute path to the saved PNG file.
    """
    out_root = Path(output_dir) if output_dir else _DEFAULT_OUTPUT
    out_root.mkdir(parents=True, exist_ok=True)
    out_path = _resolve_capture_path(out_root, name)

    saved = await capture_single_url(url, out_path, selector)
    return str(saved)


@mcp.tool()
async def capture_element(
    url: str,
    selector: str,
    name: str,
    output_dir: Optional[str] = None,
) -> str:
    """
    Navigate to a URL and capture a specific DOM element.

    Args:
        url: Full URL to navigate to.
        selector: CSS selector for the element to capture.
        name: Filename stem for the PNG.
        output_dir: Where to save the PNG.

    Returns:
        Absolute path to the saved PNG file.
    """
    out_root = Path(output_dir) if output_dir else _DEFAULT_OUTPUT
    out_root.mkdir(parents=True, exist_ok=True)
    out_path = _resolve_capture_path(out_root, name)

    saved = await capture_single_url(url, out_path, selector)
    return str(saved)


@mcp.tool()
async def run_flow_tool(
    flow_name: str,
    config_path: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> list[str]:
    """
    Execute a named flow from a TOML config file.

    Args:
        flow_name: Name of the flow to run (must exist in the config).
        config_path: Path to TOML config. Falls back to SCREENWRIGHT_CONFIG env var.
        output_dir: Override the output directory from the config.

    Returns:
        List of absolute paths to all captured PNG files, followed by the .webm
        recording path if the flow has `record = true` set.
    """
    cfg = _resolve_config(config_path)
    flow_def = cfg.get_flow(flow_name)
    if flow_def is None:
        available = ", ".join(cfg.flow_names()) or "(none)"
        raise ValueError(f"Flow {flow_name!r} not found. Available: {available}")

    out_root = _resolve_output(cfg, output_dir)
    result: FlowResult = await run_flow(flow_def, cfg, out_root)
    paths = [str(c.path) for c in result.captures]
    if result.video_path is not None:
        paths.append(str(result.video_path))
    return paths


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
async def describe_screenshot(
    screenshot_path: str,
    provider: str = "anthropic",
    model: str = "claude-haiku-4-5",
    structured_metadata: bool = True,
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

    Returns:
        Description string, or JSON string when structured_metadata is true.
    """
    from screenwright.config import VisionConfig
    from screenwright.vision import describe

    path = Path(screenshot_path)
    if not path.exists():
        raise FileNotFoundError(f"Screenshot not found: {screenshot_path}")

    vision_cfg = VisionConfig(
        provider=provider,  # type: ignore[arg-type]
        model=model,
        structured_metadata=structured_metadata,
    )

    loop = asyncio.get_event_loop()
    metadata = await loop.run_in_executor(None, describe, path, vision_cfg)

    if structured_metadata:
        import json

        return json.dumps(metadata.model_dump(), indent=2)
    return metadata.description


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
