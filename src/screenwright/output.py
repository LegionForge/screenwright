from __future__ import annotations

import json
from pathlib import Path

from screenwright.capture import CaptureResult, FlowResult


def save_metadata(capture: CaptureResult, output_root: Path) -> Path:
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
    lines = [
        f"# {flow_result.flow_name}",
        "",
        "| Screenshot | Description |",
        "|------------|-------------|",
    ]
    for capture in flow_result.captures:
        img_ref = f"![]({capture.capture_name}.png)"
        if capture.metadata:
            desc = capture.metadata.description.replace("\n", " ").strip()
        else:
            desc = ""
        lines.append(f"| {img_ref} | {desc} |")
    lines.append("")
    return "\n".join(lines)


def _root_readme_md(flow_results: list[FlowResult]) -> str:
    lines = [
        "# Screenwright Output",
        "",
        "| Flow | Screenshots | Index |",
        "|------|-------------|-------|",
    ]
    for fr in flow_results:
        count = len(fr.captures)
        lines.append(
            f"| {fr.flow_name} | {count} | [{fr.flow_name}/index.md]({fr.flow_name}/index.md) |"
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
