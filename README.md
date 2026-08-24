<p align="center">
  <a href="https://legionforge.org">
    <img src="https://assets.legionforge.org/current/logos/legionforge-logo-color.svg" alt="LegionForge" height="64">
  </a>
</p>

# Screenwright

A focused documentation screenshot pipeline with an MCP server interface, built by [LegionForge](https://legionforge.org). Screenwright sits on top of Playwright (Python) and a vision model to capture UI screenshots at critical flow points and produce GitHub-documentation-ready output: organized PNGs, structured metadata JSON, and auto-generated markdown with descriptions and alt text.

---

## Why Screenwright?

`playwright-mcp` and similar tools are excellent for ad-hoc browser automation. They are not documentation pipelines. Screenwright adds:

- **Config-driven flows** — define your capture sequence once in TOML, run it anywhere
- **Vision-generated descriptions** — Claude Haiku, OpenAI, or local Moondream2 describes each screenshot
- **Client-agnostic MCP server** — driven the same way from Claude Desktop, Claude Code, or OpenAI Codex CLI
- **Structured metadata** — JSON sidecar per screenshot (components, state, accessibility notes)
- **Docs-ready output** — organized PNGs + auto-generated markdown index, ready for GitHub

See [DECISIONS.md](DECISIONS.md) for a full survey of existing tools and the design rationale.

**Further docs:** [Architecture](docs/ARCHITECTURE.md) (module map + diagrams) ·
[MCP Tools Reference](docs/MCP_TOOLS.md) (for agents/clients) ·
[Python API Reference](docs/API_REFERENCE.md) (for library use) ·
[Wiki](https://github.com/LegionForge/screenwright/wiki) ·
[Code tour](.tours/getting-started.tour) (open with the [CodeTour extension](https://marketplace.visualstudio.com/items?itemName=vsls-contrib.codetour))

---

## Installation

```bash
pip install screenwright
playwright install chromium
```

For the Claude Haiku vision model:
```bash
export ANTHROPIC_API_KEY=your-api-key
```

For an OpenAI vision model (e.g. `gpt-4o-mini`):
```bash
export OPENAI_API_KEY=your-api-key
```

For the local Moondream2 vision model (no API key required):
```bash
# Install Ollama: https://ollama.com
ollama pull moondream
```

---

## Quick Start — CLI

Create a config file (see `examples/basic.toml`):

```toml
[screenwright]
output_dir = "docs/screenshots"
base_url   = "https://example.com"

[vision]
provider = "anthropic"
model    = "claude-haiku-4-5"
structured_metadata = true

[[flows]]
name = "homepage"

  [[flows.steps]]
  action = "navigate"
  url    = "/"

  [[flows.steps]]
  action = "capture"
  name   = "homepage-full"
```

Run it:

```bash
screenwright run basic.toml
```

Run a single flow from a multi-flow config:

```bash
screenwright run flow.toml --flow login-flow
```

List flows in a config without running:

```bash
screenwright flows flow.toml
```

Output will be organized as:

```
docs/screenshots/
  homepage/
    homepage-full.png
    homepage-full.json       # structured metadata (when structured_metadata = true)
    index.md
  README.md
```

---

## MCP Server Setup

Add Screenwright to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "screenwright": {
      "command": "screenwright-mcp",
      "env": {
        "ANTHROPIC_API_KEY": "your-api-key",
        "SCREENWRIGHT_CONFIG": "/path/to/your/config.toml"
      }
    }
  }
}
```

For Claude Code, add to `.mcp.json` in your project root:

```json
{
  "mcpServers": {
    "screenwright": {
      "command": "screenwright-mcp",
      "env": {
        "SCREENWRIGHT_CONFIG": "./screenwright.toml"
      }
    }
  }
}
```

For OpenAI Codex CLI, add to `~/.codex/config.toml` (or your project's `.codex/config.toml`):

```toml
[mcp_servers.screenwright]
command = "screenwright-mcp"
args = []

[mcp_servers.screenwright.env]
SCREENWRIGHT_CONFIG = "./screenwright.toml"
```

For **VS Code** (native MCP support) or **VSCodium**, add to `.vscode/mcp.json` in your
workspace:

```json
{
  "servers": {
    "screenwright": {
      "type": "stdio",
      "command": "screenwright-mcp",
      "env": {
        "SCREENWRIGHT_CONFIG": "${workspaceFolder}/screenwright.toml"
      }
    }
  }
}
```

For **Kilo Code** (VS Code extension), add to its MCP settings (Kilo Code panel → MCP Servers →
Edit Global/Project MCP, or the extension's `mcp_settings.json`) — same shape as Claude
Desktop's:

```json
{
  "mcpServers": {
    "screenwright": {
      "command": "screenwright-mcp",
      "env": {
        "SCREENWRIGHT_CONFIG": "/path/to/your/config.toml"
      }
    }
  }
}
```

For **OpenCode**, add to `opencode.json` (project root or `~/.config/opencode/opencode.json`):

```json
{
  "mcp": {
    "screenwright": {
      "type": "local",
      "command": ["screenwright-mcp"],
      "environment": {
        "SCREENWRIGHT_CONFIG": "./screenwright.toml"
      }
    }
  }
}
```

Screenwright's MCP server is a standard stdio server built on the `mcp` Python SDK — it isn't
Claude-specific, so any MCP-compliant client can drive it the same way; only the config file's
name/shape differs per client. Only the *vision* layer cares which AI vendor you're using — set
`provider = "openai"` in `[vision]` (with `OPENAI_API_KEY` set) if you'd rather keep the whole
pipeline on OpenAI, or `provider = "ollama"` to keep it fully local regardless of which client
is driving Screenwright.

MCP config file locations and formats change between client versions faster than this README
does — check your client's current docs if one of the snippets above doesn't connect.

### MCP Tools

| Tool | Description |
|------|-------------|
| `capture_url(url, name, selector?)` | Capture full page or element at a URL |
| `capture_element(url, selector, name)` | Capture a specific DOM element |
| `run_flow_tool(flow_name, config_path?)` | Execute a named flow from the loaded config |
| `list_flows(config_path?)` | List available flow names |
| `describe_screenshot(screenshot_path, vision_model?)` | Describe a PNG using the vision model |

---

## Config Reference

### `[screenwright]` section

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `output_dir` | string | `"docs/screenshots"` | Where to write PNGs and markdown |
| `base_url` | string | `""` | Base URL prepended to relative paths in `navigate` steps |
| `vision_describe` | bool | `true` | Whether to call the vision model at all |

### `[vision]` section

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `provider` | string | `"anthropic"` | `"anthropic"`, `"openai"`, or `"ollama"` |
| `model` | string | `"claude-haiku-4-5"` | Model name. For OpenAI: `"gpt-4o-mini"`. For Ollama: `"moondream"`, `"llava"`, `"qwen2-vl"` |
| `structured_metadata` | bool | `true` | Return JSON metadata alongside plain description |
| `prompt` | string | *(built-in)* | Override the describe prompt sent to the vision model |

### Flow steps

| Action | Required fields | Optional fields | Description |
|--------|----------------|-----------------|-------------|
| `navigate` | `url` | `wait_until` (`load` default, or `domcontentloaded`/`networkidle`/`commit`) | Navigate to URL (relative to `base_url` if starts with `/`). Use `domcontentloaded` for apps with persistent websocket/SSE connections (live dashboards, log viewers) — `networkidle` will time out on them since the connection never goes idle. |
| `capture` | `name` | `selector` | Screenshot the page or a CSS-selected element |
| `fill` | `selector`, `value` | `secret` (bool, default `false`) | Fill an input field. `value` may be `${ENV_VAR}` to pull from the environment instead of a literal — required (not optional) when `secret = true`, so a credential can't accidentally end up committed as plaintext next to the flow that uses it. |
| `click` | `selector` | — | Click an element |
| `wait` | `ms` | — | Wait N milliseconds |
| `hover` | `selector` | — | Hover over an element (triggers `:hover` CSS / `mouseenter`/`mouseover` — capture right after to catch hover states, tooltips, CSS-driven dropdown menus) |
| `press` | `selector`, `key` | — | Press a keyboard key |
| `check` | `selector` | `checked` (bool, default `true`) | Check or uncheck a checkbox/radio input |
| `select` | `selector`, `value` | — | Choose an option in a native `<select>` by its `value` attribute |

---

## Capturing Interactive UI States

`hover`, `check`, and `select` exist specifically to capture non-default UI states for docs —
a hovered button/tooltip, a checked checkbox, a selected dropdown option — by driving the real
DOM state and then following with a `capture` step. Typical pattern:

```toml
[[flows.steps]]
action = "hover"
selector = "#nav-menu-trigger"

[[flows.steps]]
action = "capture"
name = "menu-hover-state"
```

**One hard limitation, not specific to Screenwright:** native OS-rendered `<select>` dropdown
popups (the list that drops down when you click a plain HTML select) are drawn by the operating
system, not the page's DOM — no browser automation tool (Playwright, Puppeteer, Selenium, or a
live Chrome extension like Claude-in-Chrome) can screenshot that open popup. `select` sets the
*chosen* value and lets you capture the resulting state, but not the open-popup moment itself.
Custom combobox widgets built from regular DOM elements (React-select, MUI Select, Radix,
Headless UI, etc.) don't have this limitation — they render as normal elements, so `click` +
`capture` (or `hover` + `capture` for CSS-driven menus) captures the open state fine.

---

## Credentials in Login Flows

If a flow needs to fill a password, API token, or anything else sensitive, don't put the literal
value in the TOML:

```toml
[[flows.steps]]
action = "fill"
selector = "#password"
value = "${DB_PASSWORD}"   # resolved from the environment at run time
secret = true               # required (not optional) once secret = true
```

`secret = true` requires `value` to be an `${ENV_VAR}` reference — Screenwright refuses to load
a config where a step is marked `secret` but the value is a literal string, so a real credential
can't accidentally end up committed in plaintext next to the flow that uses it. `${ENV_VAR}`
interpolation also works on non-secret `fill` steps, if you just want a dynamic value without the
stricter check.

This only controls what's *typed into the page* — it does not redact what a subsequent
`capture` step sees. If a screenshot of that field must not show the value, mask it in the UI
itself or don't add a `capture` step until after the field is cleared/hidden.

---

## Video Recording

Set `record = true` on a flow to record the entire flow as a `.webm` video alongside its screenshots:

```toml
[[flows]]
name = "signup-demo"
record       = true
record_width  = 1280   # optional, default 1280
record_height = 720    # optional, default 720
record_mp4    = true   # optional — also convert to mp4 (requires ffmpeg on PATH)

  [[flows.steps]]
  action = "navigate"
  url    = "/signup"

  # ...fill, click, wait, capture steps as usual
```

Recording is scoped to the whole flow (Playwright ties video capture to a browser context,
not individual steps), so it can't be started/stopped partway through a flow — split into
multiple flows if you only want part of a sequence recorded.

`record_mp4` shells out to `ffmpeg` (`brew install ffmpeg` on macOS) to transcode the `.webm`
to H.264 `.mp4` after recording finishes. Without it, output stays `.webm` — fine for GitHub
READMEs and most players, but not for direct upload to LinkedIn/YouTube (see below).

---

## Output Format

### `{flow_name}/{capture_name}.png`
Full-page or element screenshot.

### `{flow_name}/{capture_name}.json` *(when `structured_metadata = true`)*
```json
{
  "description": "Login form with email and password fields",
  "components": ["form", "input", "button"],
  "state": "empty",
  "title": "Sign In",
  "errors_visible": false,
  "accessibility_notes": "Password field lacks a visible label"
}
```

### `{flow_name}/index.md`
Markdown table listing all captures with their descriptions.

### `README.md` (output root)
Table of all flows with links to their index files.

---

## Vision Model Setup

### Claude Haiku (default — cloud)

Requires an Anthropic API key. Set `ANTHROPIC_API_KEY` in your environment.

```toml
[vision]
provider = "anthropic"
model    = "claude-haiku-4-5"
structured_metadata = true
```

Cost: ~$0.25/M input tokens. Describing a typical UI screenshot costs a fraction of a cent.

### OpenAI (cloud)

Requires an OpenAI API key. Set `OPENAI_API_KEY` in your environment. Useful when the rest of
your workflow — e.g. driving Screenwright's MCP server from Codex CLI — is already on OpenAI.

```toml
[vision]
provider = "openai"
model    = "gpt-4o-mini"
structured_metadata = true
```

### Moondream2 (local — no API key)

[Install Ollama](https://ollama.com), then pull the model:

```bash
ollama pull moondream
```

```toml
[vision]
provider = "ollama"
model    = "moondream"
structured_metadata = true
```

Moondream2 is the recommended default for air-gapped environments or UIs with sensitive data that should not leave your network. Other Ollama vision models (`llava`, `qwen2-vl`) also work — set `model` accordingly.

> **Note:** Moondream2 is a small (~1.6B) model and can return an empty response when asked to follow the structured JSON prompt (`structured_metadata = true`). Screenwright falls back gracefully to an empty description rather than failing the run, but for reliable structured metadata with Moondream, either set `structured_metadata = false` or use a larger local model such as `llava` or `qwen2-vl`.

### Disable vision entirely

```toml
[screenwright]
vision_describe = false
```

---

## Roadmap

| Use case | Status |
|----------|--------|
| **a) TOML/URL-list driven capture** — CLI tool with flow definitions | ✅ Implemented |
| **b) MCP server** — LLM-controlled capture with `mcp` SDK | ✅ Implemented |
| **c) FastAPI auto-discovery** — crawl `/openapi.json`, auto-generate flows | 🏗 Scaffolded (see `discovery.py`) |
| **d) Guided tour UI** — interactive walkthrough from capture output | ❌ Out of scope (deferred) |

---

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
pytest
```

---

## Support LegionForge

Screenwright is free and MIT-licensed. If it's useful to you and you'd like to support ongoing
LegionForge open-source work:

- [legionforge.org/donations](https://legionforge.org/donations/)
- [Ko-fi](https://ko-fi.com/jp_cruz)
- [Patreon](https://patreon.com/cw/JPCruz)
