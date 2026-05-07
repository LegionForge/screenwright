# Screenwright — Architecture Decisions

Architecture decisions, research findings, and rationale behind the tool's design.

---

## 1. Why not just use `microsoft/playwright-mcp`?

`playwright-mcp` is a general browser automation tool. It exposes raw Playwright actions (click, navigate, fill) as MCP tools and is excellent for ad-hoc browser control by an LLM. It is not a documentation pipeline:

- No concept of a "flow" — an ordered, repeatable sequence of steps with capture points
- No config-driven definition; every run is a one-off controlled by the model
- No output organization (named PNGs in a docs-ready directory structure)
- No vision-model integration for auto-generated alt text / descriptions
- No markdown index generation

Screenwright is a layer above browser automation tools. It is opinionated about *documentation output*, not browser control.

---

## 2. Why Playwright over Puppeteer or Selenium?

- **Python-native**: first-class async Python API; no Node.js dependency
- **Multi-browser**: Chromium, Firefox, WebKit from one API
- **Element-level screenshots**: `element.screenshot()` is built in — no coordinate math or clipping
- **Active maintenance**: Backed by Microsoft, released frequently, and widely used in Python test ecosystems
- **`networkidle` wait strategy**: cleaner for documentation captures than arbitrary sleeps

Selenium was ruled out: its element screenshot support requires additional libraries and its WebDriver protocol is slower than Playwright's CDP bridge. Puppeteer was ruled out: Node.js only.

---

## 3. Vision model strategy

Two options are supported, selectable via `vision_model` in the TOML config:

| Option | Model | API key required | GPU required | Best for |
|--------|-------|-----------------|--------------|----------|
| `claude-haiku` (default) | Claude Haiku (claude-haiku-4-5) | Yes (ANTHROPIC_API_KEY) | No | Cloud / fast / low cost |
| `moondream` | Moondream2 via Ollama | No | Recommended | Air-gapped / private UI |

**Claude Haiku** is the default. At ~$0.25/M input tokens with vision support, describing a typical UI screenshot costs a fraction of a cent. It requires no local GPU and produces high-quality, concise documentation-ready text.

**Moondream2** is the local fallback. It runs via Ollama (`ollama pull moondream`) and requires no API key. It is well-suited for environments where screenshots may contain sensitive internal UI that should not be sent to an external API.

The vision step is optional — set `vision_describe = false` to skip it entirely and produce PNGs without descriptions.

---

## 4. MCP server design: stdio transport

The MCP server uses stdio transport (stdin/stdout) via FastMCP. Rationale:

- **Universal compatibility**: stdio works with Claude Desktop, Claude Code, and any MCP-compliant client without network configuration
- **No port management**: avoids port conflicts in multi-tool setups
- **Process isolation**: each client gets its own process with its own Playwright browser context
- **Simpler deployment**: the server entry point (`screenwright-mcp`) is just a process the client spawns; no daemon management

HTTP/SSE transport could be added in future for multi-client scenarios, but stdio is the right starting point.

---

## 5. Existing tools surveyed

| Tool | Type | Gap |
|------|------|-----|
| `microsoft/playwright-mcp` | MCP server (Node.js) | General automation; no docs pipeline |
| `mcp-playwright` (ExecuteAutomation) | MCP server (Node.js) | General test automation; no flow config |
| `browserloop` | MCP server | Single URL capture on demand; no flows |
| `mcp-screenshot-server` (sethbang) | MCP server | URL-to-PNG only; no vision integration |
| ScreenshotOne MCP | MCP server (SaaS wrapper) | Cloud dependency; no self-hosted capture |
| VeryInt Playwright Screenshot MCP | MCP server | Single-shot capture; no flow definitions |

None of these tools produce structured, docs-ready output from a declarative flow definition with vision-generated descriptions. That is the gap Screenwright fills.

---

## 6. Use case d (guided tour UI) deferred

A guided tour UI would embed Screenwright captures into an interactive walkthrough (tooltips, step highlights, animated transitions). This requires:

- A JavaScript/web component or SPA framework for the tour UI
- A hosting strategy (embed in existing app, standalone web page, or Electron)
- Integration with the capture output format

Use cases a and b (CLI pipeline and MCP server) cover the primary automated documentation use cases. The guided tour is a significant frontend build and is deferred until the core pipeline is proven in production use.

---

## 7. Use case c (FastAPI auto-discovery) scaffolded, not implemented

The concept: given a running FastAPI app, fetch `/openapi.json`, enumerate GET routes, and auto-generate a Screenwright TOML that navigates to each route and captures a screenshot.

The obstacle is the API-to-UI mapping problem: OpenAPI describes API routes, not frontend routes. A FastAPI backend serving `/api/v1/users` likely has a frontend at `/users` or `/admin/users`. There is no general mapping without conventions or annotations.

Possible future approaches:
- Allow a URL prefix rewrite rule in the config (`api_prefix = "/api/v1"`, `ui_prefix = "/"`)
- Require FastAPI to annotate routes with `x-ui-path` extensions
- Detect if the route returns HTML (Content-Type `text/html`) vs JSON

Scaffolded in `discovery.py` with a detailed TODO. Will revisit after the core pipeline has real-world usage data to inform what users actually need.
