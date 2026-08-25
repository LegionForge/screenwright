# MCP Tools Reference

For AI agents driving `screenwright-mcp`, and for developers wiring it into a client. Server is
a standard [`mcp`](https://pypi.org/project/mcp/) Python SDK stdio server — see `mcp_server.py`.
Client setup per host (Claude Desktop/Code, Codex CLI, VS Code, VSCodium, Kilo Code, OpenCode) is
in the README's [MCP Server Setup](../README.md#mcp-server-setup) section.

```mermaid
flowchart LR
    subgraph Clients
        CD["Claude Desktop"]
        CC["Claude Code"]
        CX["Codex CLI"]
        VS["VS Code / VSCodium"]
        KC["Kilo Code"]
        OC["OpenCode"]
    end
    MCP["screenwright-mcp\n(stdio, FastMCP)"]
    CD & CC & CX & VS & KC & OC -->|MCP tool calls, stdio| MCP
    MCP --> CAP["capture.py"]
    MCP --> VIS["vision.py"]
```

Config resolution for every tool: an explicit `config_path` argument wins; otherwise the server
falls back to the `SCREENWRIGHT_CONFIG` environment variable set in the client's MCP config; if
neither is set, an empty default `ScreenwrightConfig()` is used (fine for `capture_url`/
`capture_element`, which don't need flows).

---

## `capture_url`

Navigate to a URL and capture a screenshot. No config file needed.

| Param | Type | Required | Description |
|---|---|---|---|
| `url` | string | yes | Full URL to navigate to |
| `name` | string | yes | Filename stem for the PNG (no extension) |
| `selector` | string | no | CSS selector — captures only that element instead of full page |
| `output_dir` | string | no | Where to save the PNG. Defaults to a temp directory |
| `wait_until` | `"load" \| "domcontentloaded" \| "networkidle" \| "commit"` | no | Default `"load"`. Use `"networkidle"` cautiously — a page with a persistent websocket/SSE connection never goes network-idle and hangs until `timeout_ms` |
| `timeout_ms` | int | no | Navigation timeout in milliseconds. Default `30000` |
| `viewport_width` | int | no | Default `1280` — e.g. `390` for a mobile-sized capture |
| `viewport_height` | int | no | Default `720` |
| `animations` | `"disabled" \| "allow"` | no | Default `"disabled"` — freezes CSS animations for a deterministic screenshot |

**Returns:** `string` — absolute path to the saved PNG.

**Example call (as an agent would invoke it):**
```json
{"tool": "capture_url", "arguments": {"url": "https://example.com", "name": "homepage"}}
```

## `capture_element`

Same as `capture_url` but `selector` is required — captures one DOM element.

| Param | Type | Required | Description |
|---|---|---|---|
| `url` | string | yes | Full URL to navigate to |
| `selector` | string | yes | CSS selector for the element |
| `name` | string | yes | Filename stem for the PNG |
| `output_dir` | string | no | Where to save the PNG |
| `wait_until` | `"load" \| "domcontentloaded" \| "networkidle" \| "commit"` | no | Same as `capture_url` |
| `timeout_ms` | int | no | Same as `capture_url` |
| `viewport_width` | int | no | Same as `capture_url` |
| `viewport_height` | int | no | Same as `capture_url` |
| `animations` | `"disabled" \| "allow"` | no | Same as `capture_url` |

**Returns:** `string` — absolute path to the saved PNG.

## `run_flow_tool`

Execute a named flow from a TOML config — the multi-step, potentially video-recording path.

| Param | Type | Required | Description |
|---|---|---|---|
| `flow_name` | string | yes | Name of the flow to run (must exist in the config) |
| `config_path` | string | no | Path to TOML config. Falls back to `SCREENWRIGHT_CONFIG` |
| `output_dir` | string | no | Override the config's `output_dir` |
| `vision_describe` | bool | no | Default `false`. When true, describes each capture with the config's vision provider and writes `{name}.json` sidecars (+ regenerates `index.md`) — the same auto-describe step `cli.py`'s `run` does. Without this, `describe_flow` afterward has nothing to bundle unless you call `describe_screenshot` per capture yourself; see [Error handling for agents](#error-handling-for-agents) below |

**Returns:** a dict:
```json
{
  "captures": ["<absolute PNG path>", "..."],
  "video_path": "<absolute .webm path> | null",
  "video_mp4_path": "<absolute .mp4 path> | null",
  "error": "<string> | null",
  "failed_step_index": "<int> | null"
}
```

If a step fails mid-flow, this does **not** raise — `captures` still contains everything
captured before the failure, `error`/`failed_step_index` describe what went wrong, and any
in-progress video recording is still finalized (Playwright only flushes a `.webm` on context
close, so a naive implementation would lose the whole recording on a mid-flow error — this one
doesn't). An agent should treat a non-null `error` as "partial success, here's what happened,"
not as a failed tool call.

**Raises:** `ValueError` only for a missing `flow_name` (message includes the list of available
flow names) or a config-loading error — never for a step failing during the flow itself.

## `list_flows`

| Param | Type | Required | Description |
|---|---|---|---|
| `config_path` | string | no | Path to TOML config. Falls back to `SCREENWRIGHT_CONFIG` |

**Returns:** `list[string]` — flow names defined in the config.

## `describe_flow`

Return everything already captured for a flow — the markdown index and every capture's
structured metadata — in one call, instead of one `describe_screenshot` round-trip per
screenshot. Reads existing output on disk; **does not run the flow** — call `run_flow_tool`
first.

| Param | Type | Required | Description |
|---|---|---|---|
| `flow_name` | string | yes | Name of a flow that has already been run. Must match `^[A-Za-z0-9._-]+$` and not be a path-traversal segment — same validation as `capture_url`/`capture_element`'s `name` param, since this builds a filesystem path |
| `config_path` | string | no | Path to TOML config, used only to resolve `output_dir` the same way `run_flow_tool` does. Falls back to `SCREENWRIGHT_CONFIG` |
| `output_dir` | string | no | Override the output directory from the config |

**Returns:** a dict:
```json
{
  "flow_name": "homepage",
  "index_md": "<markdown index content> | null",
  "captures": [
    {"name": "hero", "path": "<absolute PNG path>", "metadata": {"description": "...", "...": "..."}},
    {"name": "footer", "path": "<absolute PNG path>", "metadata": null}
  ]
}
```

`index_md` is `null` and `captures` is `[]` if the flow's output directory doesn't exist yet
(it hasn't been run). A capture with no `.json` sidecar — the common case being `run_flow_tool`
was called without `vision_describe=true` (its default), or `describe()` failing for just that
one — has `metadata: null` rather than being silently dropped from the bundle.

## `describe_screenshot`

Send an already-captured PNG to a vision model independently of a flow run.

| Param | Type | Required | Description |
|---|---|---|---|
| `screenshot_path` | string | yes | Absolute path to the PNG |
| `provider` | `"anthropic" \| "ollama" \| "openai"` | no | `"anthropic"` (default) |
| `model` | string | no | Model name — e.g. `"claude-haiku-4-5"`, `"gpt-4o-mini"`, `"moondream"` |
| `structured_metadata` | bool | no | Default `true` — return JSON metadata instead of plain text |
| `prompt` | string | no | Custom instruction for the vision model — e.g. `"Focus on accessibility issues"` or `"Describe in Spanish"`. Defaults to Screenwright's built-in generic description prompt. When `structured_metadata=true`, the JSON-structure instruction is still appended after this prompt, same as a TOML-configured `[vision] prompt` |

**Returns:** `string` — JSON-encoded `ScreenshotMetadata` if `structured_metadata=true`, else the
plain-text description.

**Raises:** `FileNotFoundError` if `screenshot_path` doesn't exist; `ValueError` if the file isn't
actually a PNG (checked by magic bytes, not extension — `screenshot_path` can come from an LLM
acting on untrusted page content, and this tool base64-encodes the whole file and forwards it to
a third-party vision API, so this closes an arbitrary-local-file-read/exfiltration path an
extension check alone wouldn't); Pydantic `ValidationError` if `provider` is set to a value
outside the three above (a real MCP client sees the valid options in the tool's schema, so this
is a fallback for a client that ignores it).

---

## Error handling for agents

Transient failures already retry internally, so an agent shouldn't blindly re-issue the same
call hoping a retry helps — that's already handled. `capture_url`/`capture_element`/
`run_flow_tool` retry a navigation that fails with a Playwright timeout or a `net::ERR_*`
network error up to 2x with exponential backoff before surfacing anything; `describe_screenshot`
similarly retries a transient provider failure (429/5xx, timeout) up to 2x. `run_flow_tool` only
calls a vision provider when `vision_describe=true` is passed (default `false`) — with the
default, it's pure capture, no `describe()` call, no vision retries in play at all. When
`vision_describe=true` *is* set, each capture's `describe()` call still goes through the same
retry path as `describe_screenshot`, but a failure that survives those retries is swallowed per
capture rather than surfaced — that capture's `.json` sidecar simply isn't written, the flow
call itself doesn't fail. `describe_flow` never calls a vision provider either way; it only
reads whatever `.json` sidecars already exist on disk. See [Architecture](ARCHITECTURE.md) for
the exact retry policy.

What isn't retried, and what an agent should treat as a real, informative failure rather than
transient — a bad `selector`, a missing/invalid API key, a wrong `flow_name`, or a navigation
failure that didn't clear after the internal retries: `capture_url`/`capture_element`/
`describe_screenshot` surface this as a raised exception the MCP client displays as a tool
error. `run_flow_tool` is the one exception — it never raises for a step failing mid-flow; it
returns a non-null `error` field instead, alongside whatever was already captured. An agent
should adjust the next call (a different selector, a
corrected flow name) rather than retry the same arguments.
