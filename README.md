# Screenwright

A focused documentation screenshot pipeline with an MCP server interface. Screenwright sits on top of Playwright (Python) and a vision model to capture UI screenshots at critical flow points and produce GitHub-documentation-ready output: organized PNGs, structured metadata JSON, and auto-generated markdown with descriptions and alt text.

---

## Why Screenwright?

`playwright-mcp` and similar tools are excellent for ad-hoc browser automation. They are not documentation pipelines. Screenwright adds:

- **Config-driven flows** — define your capture sequence once in TOML, run it anywhere
- **Vision-generated descriptions** — Claude Haiku or local Moondream2 describes each screenshot
- **Structured metadata** — JSON sidecar per screenshot (components, state, accessibility notes)
- **Docs-ready output** — organized PNGs + auto-generated markdown index, ready for GitHub

See [DECISIONS.md](DECISIONS.md) for a full survey of existing tools and the design rationale.

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

For Claude Code, add to `.claude/settings.json`:

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
| `provider` | string | `"anthropic"` | `"anthropic"` or `"ollama"` |
| `model` | string | `"claude-haiku-4-5"` | Model name. For Ollama: `"moondream"`, `"llava"`, `"qwen2-vl"` |
| `structured_metadata` | bool | `true` | Return JSON metadata alongside plain description |
| `prompt` | string | *(built-in)* | Override the describe prompt sent to the vision model |

### Flow steps

| Action | Required fields | Optional fields | Description |
|--------|----------------|-----------------|-------------|
| `navigate` | `url` | — | Navigate to URL (relative to `base_url` if starts with `/`) |
| `capture` | `name` | `selector` | Screenshot the page or a CSS-selected element |
| `fill` | `selector`, `value` | — | Fill an input field |
| `click` | `selector` | — | Click an element |
| `wait` | `ms` | — | Wait N milliseconds |
| `hover` | `selector` | — | Hover over an element |
| `press` | `selector`, `key` | — | Press a keyboard key |

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
