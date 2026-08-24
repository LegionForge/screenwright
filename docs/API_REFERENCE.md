# Python API Reference

For developers importing `screenwright` as a library instead of using the CLI/MCP server. All
public functions are `async` except `load_config`. See [Architecture](ARCHITECTURE.md) for how
these fit together, and [MCP Tools](MCP_TOOLS.md) if you're driving Screenwright from an agent
instead of Python directly.

## `screenwright.config`

### `load_config(path: str | Path) -> ScreenwrightConfig`
Parse a TOML file into a validated config object. Raises a Pydantic `ValidationError` on schema
violations (unknown step `action`, missing required field, etc.) — errors point at the exact
field.

### `ScreenwrightConfig`
| Field | Type | Default |
|---|---|---|
| `output_dir` | `str` | `"docs/screenshots"` |
| `base_url` | `str` | `""` |
| `vision_describe` | `bool` | `true` |
| `vision` | `VisionConfig` | — |
| `flows` | `list[Flow]` | `[]` |

Methods: `.get_flow(name: str) -> Flow \| None`, `.flow_names() -> list[str]`.

### `Flow`
| Field | Type | Default |
|---|---|---|
| `name` | `str` | required |
| `steps` | `list[Step]` | `[]` |
| `record` | `bool` | `false` |
| `record_width` / `record_height` | `int` | `1280` / `720` |
| `record_mp4` | `bool` | `false` |
| `viewport_width` / `viewport_height` | `int` | `1280` / `720` |
| `timeout_ms` | `int` | `30000` |
| `storage_state` | `str \| None` | `None` |

### `Step`
A Pydantic discriminated union (on `action`) of: `NavigateStep`, `CaptureStep`, `FillStep`,
`ClickStep`, `WaitStep`, `HoverStep`, `PressStep`, `CheckStep`, `SelectStep`. See the
[Flow Reference](../README.md#config-reference) for each step's fields.

### `VisionConfig`
| Field | Type | Default |
|---|---|---|
| `provider` | `"anthropic" \| "ollama" \| "openai"` | `"anthropic"` |
| `model` | `str` | `"claude-haiku-4-5"` |
| `structured_metadata` | `bool` | `true` |
| `prompt` | `str` | built-in default |

---

## `screenwright.capture`

### `async run_flow(flow: Flow, config: ScreenwrightConfig, output_root: Path) -> FlowResult`
Runs every step in `flow` against a fresh Playwright `Browser`. Writes PNGs (and, if
`flow.record`, a `.webm`/`.mp4`) under `output_root / flow.name`. This is the function both the
CLI and `run_flow_tool` call — no other capture path exists.

### `async capture_single_url(url: str, output_path: Path, selector: str | None = None, wait_until: str = "load") -> Path`
One-shot capture with no flow/config needed. What `capture_url`/`capture_element` call.

### `FlowResult`
`flow_name: str`, `captures: list[CaptureResult]`, `video_path: Path | None`,
`video_mp4_path: Path | None`.

### `CaptureResult`
`flow_name: str`, `capture_name: str`, `path: Path`, `metadata: ScreenshotMetadata | None` (set
by the caller after `describe()`, not by `run_flow` itself — see the CLI's `run` command for the
ordering: capture first, describe second).

### `FfmpegNotFoundError(RuntimeError)`
Raised by the internal mp4-conversion step when `record_mp4 = true` and `ffmpeg` isn't on
`PATH`.

---

## `screenwright.vision`

### `describe(image_path: Path, cfg: VisionConfig) -> ScreenshotMetadata`
Synchronous (not async — the three provider SDKs it wraps are synchronous). Dispatches on
`cfg.provider`. Never raises on malformed model output — falls back to a raw-text description if
JSON parsing fails or a required field is missing (see `_parse_response`).

### `ScreenshotMetadata`
`description: str`, `components: list[str]`, `state: str`, `title: str`,
`errors_visible: bool`, `accessibility_notes: str`.

---

## `screenwright.output`

### `write_flow_output(flow_result: FlowResult, output_root: Path) -> Path`
Writes each capture's `{name}.json` metadata sidecar (when `.metadata` is set) and the flow's
`index.md`. Returns the `index.md` path.

### `write_root_readme(flow_results: list[FlowResult], output_root: Path) -> Path`
Writes the root `README.md` indexing every flow. Call once after all flows in a run finish.

### `save_metadata(capture: CaptureResult, output_root: Path) -> Path | None`
Writes one `{name}.json` sidecar. Returns `None` if `capture.metadata` is unset. Called
internally by `write_flow_output` — rarely needed directly.

---

## Minimal library usage

```python
import asyncio
from pathlib import Path
from screenwright.config import load_config
from screenwright.capture import run_flow
from screenwright.vision import describe
from screenwright.output import write_flow_output, write_root_readme

async def main():
    cfg = load_config("basic.toml")
    flow = cfg.get_flow("homepage")
    result = await run_flow(flow, cfg, Path(cfg.output_dir))
    if cfg.vision_describe:
        for capture in result.captures:
            capture.metadata = describe(capture.path, cfg.vision)
    write_flow_output(result, Path(cfg.output_dir))
    write_root_readme([result], Path(cfg.output_dir))

asyncio.run(main())
```

This is exactly what `cli.py`'s `run` command does per flow — reach for the CLI or MCP server
first; use the library API directly only when you need custom orchestration (e.g. running flows
in parallel, or interleaving capture with your own logic).
