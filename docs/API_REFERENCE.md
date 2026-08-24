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

Rejects (raises Pydantic `ValidationError`, doesn't silently dedupe) any two flows sharing a
`name` — every flow's output path is derived from its name, so a duplicate would silently
overwrite output.

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
| `har` | `bool` | `false` |

Rejects two `capture` steps in the same flow sharing a `name` (both would write
`{flow_dir}/{name}.png`), same failure mode and same reasoning as `ScreenwrightConfig`'s
duplicate-flow-name check, one level down.

### `Step`
A Pydantic discriminated union (on `action`) of: `NavigateStep`, `CaptureStep`, `FillStep`,
`ClickStep`, `WaitStep`, `HoverStep`, `PressStep`, `CheckStep`, `SelectStep`. See the
[Flow Reference](../README.md#config-reference) for each step's fields.

### `Variant`
One entry in `CaptureStep.variants`: `name: str`, `viewport_width: int | None`,
`viewport_height: int | None`, `color_scheme: Literal["light", "dark", "no-preference"] | None`.
Unset fields fall back to the flow's own defaults (viewport) or `"light"` (`color_scheme`) —
this fallback is resolved fresh for *each* variant, not just once at the end of the step, so a
`dark` variant followed by one that doesn't set `color_scheme` still renders `"light"`, not a
leftover `"dark"`. See [Capture Variants](../README.md#capture-variants).

`CaptureStep` also carries `animations: Literal["disabled", "allow"] = "disabled"`,
`mask: list[str] = []`, `mask_color: str | None`. See [Deterministic Captures](../README.md#deterministic-captures).
Rejects two variants in the same `CaptureStep` sharing a `name` (both would produce
`{name}-{variant.name}.png`), same reasoning as `Flow`'s duplicate-capture-name check.

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

**Never raises for a step/setup/finalize failure** — browser/context setup errors, a step that
fails mid-flow (bad selector, navigation timeout, etc.), a missing `ffmpeg` when
`record_mp4 = true`, and any failure while closing the page/context or finalizing the video/HAR
are all caught and reported via `FlowResult.error` instead. `run_flow` can still raise for a
genuine programming error outside those paths, but every documented failure mode of "running a
flow" is designed to return, not raise — callers should check `.error`/`.failed_step_index`
rather than wrapping every call in try/except.

### `async capture_single_url(url: str, output_path: Path, selector: str | None = None, wait_until: str = "load", timeout_ms: int = 30000, viewport_width: int = 1280, viewport_height: int = 720, animations: str = "disabled") -> Path`
One-shot capture with no flow/config needed. What `capture_url`/`capture_element` call. Unlike
`run_flow`, this *does* raise on failure (a bad `selector`, a navigation error) — there's no
`FlowResult` to report a partial outcome on for a single capture. The launched browser is always
closed even on failure (try/finally), so a caller retrying with a different `selector` after a
"Selector not found" error doesn't leak a browser process per attempt.

### `FlowResult`
`flow_name: str`, `captures: list[CaptureResult]`, `video_path: Path | None`,
`video_mp4_path: Path | None`, `har_path: Path | None` (set when the flow's `har = true`),
`failed_step_index: int | None` (0-based index into `flow.steps` of the step that failed, if
any), `error: str | None` (human-readable description of what failed — a step failure, a setup
failure, an mp4-conversion failure, a video/HAR finalize failure, or several of these chained
with `; ` if more than one occurred). `error is None` means the flow completed every step and
finalized cleanly; `captures`/`video_path` etc. can still be non-empty even when `error` is set —
everything captured before a mid-flow failure is preserved, not discarded.

### `CaptureResult`
`flow_name: str`, `capture_name: str`, `path: Path`, `metadata: ScreenshotMetadata | None` (set
by the caller after `describe()`, not by `run_flow` itself — see the CLI's `run` command for the
ordering: capture first, describe second), `accessibility_path: Path | None` (set by `run_flow`
itself when the step's `accessibility_snapshot = true`), `pdf_path: Path | None` (set when the
step's `pdf = true`). One `CaptureResult` is produced per variant when the step sets `variants` —
`capture_name` becomes `{step.name}-{variant.name}` in that case, and no unsuffixed result is
produced.

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
`index.md`. Returns the `index.md` path. If `flow_result.error` is set, `index.md` gets a
`⚠️ Flow stopped early: {error}` banner above the capture table — everything captured before the
failure is still listed, the banner just makes the partial outcome visible in the generated docs
themselves rather than only in whatever logged the run.

### `write_root_readme(flow_results: list[FlowResult], output_root: Path) -> Path`
Writes the root `README.md` indexing every flow, with a Status column (`✅`, or `⚠️ Partial` for
any flow whose `.error` is set). Call once after all flows in a run finish.

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
