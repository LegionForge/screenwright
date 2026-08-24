from __future__ import annotations

import json
import re
from pathlib import Path

from screenwright.capture import CaptureResult, FlowResult

_HTML_TAG_RE = re.compile(r"<[^>]*>")
_MAX_DESCRIPTION_LEN = 500


def _escape_markdown_cell(text: str) -> str:
    """Make vision-model output safe to embed in a markdown table cell.

    `description` is model output derived from whatever was on the captured
    page — untrusted content, potentially shaped by a prompt-injection
    payload on the page itself. This output ends up in docs people commit
    and GitHub renders, so: strip any HTML tags (belt-and-suspenders on top
    of GitHub's own sanitizer), escape backslashes/pipes so the description
    can't break out of its table cell, collapse newlines, and cap length so
    one bad description can't balloon an index file.
    """
    text = _HTML_TAG_RE.sub("", text)
    text = text.replace("\\", "\\\\").replace("|", "\\|")
    text = text.replace("\n", " ").strip()
    if len(text) > _MAX_DESCRIPTION_LEN:
        text = text[: _MAX_DESCRIPTION_LEN - 1].rstrip() + "…"
    return text


def save_metadata(capture: CaptureResult, output_root: Path) -> Path | None:
    """Write a .json sidecar next to the PNG."""
    if capture.metadata is None:
        return None
    json_path = capture.path.with_suffix(".json")
    json_path.write_text(
        json.dumps(capture.metadata.model_dump(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return json_path


def _flow_index_md(flow_result: FlowResult) -> str:
    lines = [f"# {flow_result.flow_name}", ""]
    if flow_result.error is not None:
        # A flow that stopped mid-way still writes an index for whatever it
        # captured before the failure (see run_flow's "always return a
        # FlowResult, never raise" contract) — without this, that partial
        # success and the failure that caused it are only visible in
        # ephemeral CLI console output, never in the generated docs
        # themselves.
        lines.append(f"> ⚠️ **Flow stopped early:** {_escape_markdown_cell(flow_result.error)}")
        lines.append("")
    lines += [
        "| Screenshot | Description |",
        "|------------|-------------|",
    ]
    for capture in flow_result.captures:
        # capture_name is validated (config.validate_safe_name / mcp_server's
        # _resolve_capture_path) to only ever contain [A-Za-z0-9._-], so it
        # never needs URL-encoding here — unlike `desc` below, which is
        # unconstrained model output and must be escaped.
        img_ref = f"![]({capture.capture_name}.png)"
        if capture.accessibility_path is not None:
            img_ref += f" ([a11y]({capture.accessibility_path.name}))"
        if capture.pdf_path is not None:
            img_ref += f" ([pdf]({capture.pdf_path.name}))"
        desc = _escape_markdown_cell(capture.metadata.description) if capture.metadata else ""
        lines.append(f"| {img_ref} | {desc} |")
    lines.append("")

    if flow_result.video_mp4_path is not None:
        lines.append(f"[Screen recording (mp4)]({flow_result.video_mp4_path.name})")
        lines.append("")
    elif flow_result.video_path is not None:
        lines.append(f"[Screen recording (webm)]({flow_result.video_path.name})")
        lines.append("")

    return "\n".join(lines)


def _root_readme_md(flow_results: list[FlowResult]) -> str:
    lines = [
        "# Screenwright Output",
        "",
        "| Flow | Screenshots | Status | Index |",
        "|------|-------------|--------|-------|",
    ]
    for fr in flow_results:
        count = len(fr.captures)
        status = "⚠️ Partial" if fr.error is not None else "✅"
        lines.append(
            f"| {fr.flow_name} | {count} | {status} | "
            f"[{fr.flow_name}/index.md]({fr.flow_name}/index.md) |"
        )
    lines.append("")
    return "\n".join(lines)


def write_flow_output(flow_result: FlowResult, output_root: Path) -> Path:
    """Write JSON sidecars and index.md for a flow. PNGs are already on disk from capture."""
    flow_dir = output_root / flow_result.flow_name
    flow_dir.mkdir(parents=True, exist_ok=True)

    for capture in flow_result.captures:
        if capture.metadata is not None:
            save_metadata(capture, output_root)

    index_path = flow_dir / "index.md"
    index_path.write_text(_flow_index_md(flow_result), encoding="utf-8")
    return index_path


def write_root_readme(flow_results: list[FlowResult], output_root: Path) -> Path:
    readme_path = output_root / "README.md"
    readme_path.write_text(_root_readme_md(flow_results), encoding="utf-8")
    return readme_path
