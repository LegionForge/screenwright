# Improvement Backlog

Source: an independent Opus code-review pass + a market-research pass, both run 2026-08-24.
Consumed by the recurring 30-minute improvement loop (session-local cron job) — each iteration
should pick the highest-priority unchecked item, implement it with tests, verify
`pytest`/`ruff check`/`ruff format --check` are green, commit, push, and check it off here in
the same commit. Skip an iteration (no-op) rather than force a low-quality change.

## Findings (severity-ordered)

- [x] **#2 [high] Path traversal via `name`/`output_dir`** — `capture.py:127`, `capture.py:103`,
      `mcp_server.py:63,90`, `output.py:66`. `name`/`flow.name`/`output_dir` are used directly in
      path construction with no validation. On the MCP surface these come from an LLM that just
      read untrusted page content — a prompt-injection payload can steer a file write outside
      the output root. Fix: validate names against `^[A-Za-z0-9._-]+$` (reject, don't silently
      sanitize) in the Pydantic models + MCP tool bodies; resolve the final path and assert
      `is_relative_to(out_root.resolve())`. *(fixed 2026-08-24, this session)*
- [x] **#1 [high] `run_flow`'s step loop has no error handling** — `capture.py:119-173`. A step
      raising mid-flow skips video finalization (orphaned random-named `.webm`) and discards
      already-taken captures (exception propagates past `write_flow_output` in `cli.py:77`). Fix:
      wrap the loop in try/finally; in finally, close page/context and finalize video regardless;
      return a partial `FlowResult` with a `failed_step`/`error` field so CLI/MCP can report
      "3 of 5 captures succeeded, step 4 failed: selector X not found" instead of a stack trace.
      This is also **missing-feature #1** below — same fix serves both.
      *(fixed 2026-08-24: `FlowResult` gained `failed_step_index`/`error`; the step loop now
      catches per-step exceptions and always finalizes video + closes the browser in a
      try/finally; `cli.py` prints partial-failure flows distinctly; `run_flow_tool` now returns
      a `{captures, video_path, video_mp4_path, error, failed_step_index}` dict instead of a bare
      path list — a breaking MCP tool return-type change, but the package has no real external
      callers yet, so this was the right time to fix the contract rather than carry the old
      shape forward. `docs/MCP_TOOLS.md` and the wiki's MCP-Tools-Reference page updated to
      match. Tests: `test_run_flow_step_failure_returns_partial_result_not_exception`,
      `test_run_flow_with_recording_finalizes_video_on_step_failure`,
      `test_run_flow_tool_returns_partial_result_dict_on_step_failure`.)*
- [x] **#3 [medium-high] Vision-model output written unescaped into public markdown** —
      `output.py:29-34`. `description` (model output derived from attacker-controlled page
      content) goes straight into a markdown table cell with no escaping; `capture_name` isn't
      URL-encoded in the image ref. Fix: escape `|`/backticks/leading `#`, cap length,
      percent-encode filenames in image refs, consider stripping HTML tags from model output.
      *(fixed 2026-08-24: added `_escape_markdown_cell()` — strips HTML tags, escapes
      backslashes/pipes, collapses newlines, caps at 500 chars. The `capture_name`
      URL-encoding half turned out to already be covered by the earlier #2 fix:
      `validate_safe_name` constrains all names to `[A-Za-z0-9._-]`, which is already
      URL-safe — no separate encoding needed, noted with a comment in `output.py` so a future
      change to the allowed charset doesn't silently reopen this. Tests: 4 unit tests on
      `_escape_markdown_cell` + `test_write_flow_output_escapes_malicious_description`.)*
- [x] **#4 [medium-high] No env-var interpolation for `fill` values** — `config.py:31-34`,
      `capture.py:138`. Only way to script a login today is a plaintext credential in TOML next
      to the code, which then also gets screenshotted and shipped to a vision API. Fix:
      `value = "${ENV_VAR}"` resolution at load time (never render resolved values in
      logs/errors) + a `secret = true` flag on `FillStep` that masks/blocks captures.
      *(fixed 2026-08-24: `FillStep.secret` (default `false`) + a model validator requiring
      `value` to match `${ENV_VAR}` whenever `secret = true` — rejects a literal credential at
      config-load time rather than silently accepting it. `capture.py::_resolve_fill_value`
      resolves the reference at the point of use (not eagerly at config load), raising a clean
      `ValueError` naming the missing var — which the #1 fix's per-step try/except already turns
      into a `FlowResult.error` instead of a crash. Deliberately did NOT implement "masks/blocks
      captures" — that needs UI-level field masking or capture-skipping, which is a bigger,
      separate feature (see backlog feature #7, deterministic-capture helpers); this fix only
      guarantees the *config* never holds a plaintext secret, documented as a real, narrower
      scope in README/wiki. README gained a "Credentials in Login Flows" section; wiki's
      Flow-Reference page synced. Tests: 3 config-validator tests, 3 `_resolve_fill_value` unit
      tests, 2 `run_flow` integration tests (resolves + reports missing var clearly).)*
- [x] **#5 [medium] `describe()` failures abort an entire run mid-way** — `cli.py:74-77`. One
      API blip (429/timeout) raises out of the loop before `write_flow_output` — screenshots are
      on disk but no index.md, no subsequent flows run. Fix: per-capture try/except (leave
      `metadata=None`, output layer already tolerates it), bounded retry w/ exponential backoff.
      *(fixed 2026-08-24: `vision.py` gained `_with_retry`/`_is_transient` — retries up to 2x
      with exponential backoff (1s/2s) when an exception's `status_code` (or `.response.
      status_code`) is 429/500/502/503/504, or it's a `TimeoutError`/`ConnectionError`;
      deliberately does NOT retry other exceptions (bad key, malformed request) since that would
      just burn time/cost on a guaranteed-repeat failure. `describe()` now routes every provider
      call through this. `cli.py`'s per-capture loop wraps each `describe()` call in try/except —
      a failure prints a warning and leaves that capture's `metadata=None` (already tolerated by
      `output.py`) instead of aborting every remaining capture/flow. Tests: 6 retry/transient-
      detection unit tests in `test_vision.py`, 1 CLI integration test via Typer's `CliRunner`
      (`tests/test_cli.py`, new file — a first, narrow start on the "cli.py is untested"
      coverage gap below, not a full pass at it).)*
- [x] **#6 [medium] Provider response unpacking assumes a shape that isn't guaranteed** —
      `vision.py:91,137`. OpenAI `content=None` on refusal/length-stop → AttributeError, not a
      useful error. Anthropic's first content block isn't guaranteed text. `max_tokens=512`
      silently truncates+degrades with no signal. Fix: defensively locate first text block /
      handle None; surface `stop_reason == "max_tokens"` as a warning.
      *(fixed 2026-08-24: added `_first_text_block()` — scans Anthropic's `message.content` for
      the first `type == "text"` block instead of assuming index 0, returns `""` if none found
      instead of raising. OpenAI's `choice.message.content or ""` handles the `None`-on-refusal
      case the same way. Both paths now call `_warn_if_truncated()` (Python `warnings.warn`,
      `UserWarning`) when `stop_reason == "max_tokens"` (Anthropic) / `finish_reason == "length"`
      (OpenAI) — visible signal instead of a silent truncated/malformed description. Also closed
      the "zero test coverage" gap noted below for `_describe_anthropic`/`_describe_openai`:
      10 new tests mock the SDK clients directly (`monkeypatch.setattr(anthropic, "Anthropic",
      ...)` etc.) rather than the network. `_describe_ollama` remains untested — its response
      shape (plain dict) doesn't have this class of bug, lower priority.)*
- [x] **#7 [low-medium] `except (json.JSONDecodeError, Exception)` swallows everything** —
      `vision.py:54`. Narrow to `(json.JSONDecodeError, ValidationError)`. *(fixed 2026-08-24 —
      a bare `except Exception` there would also swallow real bugs unrelated to "model didn't
      return the JSON shape we asked for", e.g. a TypeError from bad input. Test forces a
      non-JSONDecodeError/ValidationError exception via monkeypatched `json.loads` and asserts
      it now propagates instead of being silently absorbed into the fallback path.)*
- [x] **mcp SDK 2.0.0 broke CI** — `mcp` shipped a breaking major release that removed
      `mcp.server.fastmcp` (rewritten around a new `mcpserver` module), and `mcp>=1.0.0` let CI
      resolve it. This is finding #8 below manifesting for real. *(pinned `mcp>=1.0.0,<2.0.0`
      2026-08-24, this session — a full migration to the 2.0 API is separate future work: the
      new module layout is `mcp.server.mcpserver` (and others) not `mcp.server.fastmcp`; read
      its actual API before migrating, don't assume it mirrors FastMCP's shape.)*
- [x] **#8 [medium, supply-chain] All 3 vision SDKs are hard runtime deps** —
      `pyproject.toml:18-20`. anthropic/openai/ollama installed unconditionally though lazily
      imported; open-ended `>=` bounds; no lockfile/hash pinning in CI. Fix: move to extras
      (`screenwright[anthropic]` etc.), clear ImportError message; pin CI with a lockfile; add
      upper bounds on fast-moving deps (playwright, mcp).
      *(partially fixed 2026-08-24: anthropic/openai/ollama moved from `dependencies` to
      per-provider extras (`anthropic`, `openai`, `ollama`, plus a `vision` extra bundling all
      three via self-referential extras); `dev` now depends on `screenwright[anthropic,openai]`
      so CI's `pip install ".[dev]"` is unaffected. Each `_describe_*` function now imports its
      SDK through `_import_provider_sdk()`, which raises a clear "pip install
      'screenwright[x]'" `ImportError` instead of a bare `ModuleNotFoundError` if the extra
      isn't installed. README + wiki (Getting-Started, Vision-Providers) updated. NOT done:
      lockfile/hash-pinning in CI, or upper bounds on playwright — left as-is since neither is
      what actually broke CI this session (that was unpinned `mcp`, already fixed separately);
      revisit if it becomes a real pain point rather than pre-emptively.)*
- [x] **#9 [low-medium] `_resolve_output` string-compares against the default as a sentinel** —
      `mcp_server.py:37`. A user who deliberately sets `output_dir = "docs/screenshots"` (the
      default value) gets silently redirected to `/tmp/screenwright-output`. Fix: use
      `model_fields_set` or make the default `None`. *(fixed 2026-08-24: switched to
      `"output_dir" in config.model_fields_set` — distinguishes "the TOML explicitly set this
      key" from "never set, holding the field default" regardless of what value was set to,
      which a value-equality check against the default string structurally can't do. 4 new
      tests, including one that would have caught the original bug directly: a config with
      `output_dir` explicitly set to the same string as the default must still resolve to that
      directory, not fall through to the temp default.)*
- [ ] **#10 [low-medium] No timeouts/viewport control anywhere** — `capture.py:88-94,119-159`.
      No `set_default_timeout`, no per-step override, `wait_until: str` untyped so a typo becomes
      a Playwright error instead of a config validation error.
- [ ] **#11 [low] `save_metadata` annotated `-> Path` but returns `None`** — `output.py:9-18`.
      mypy isn't in CI so unnoticed; fix annotation to `Path | None`.
- [x] **#12 [low] `asyncio.get_event_loop()` inside a coroutine** — `mcp_server.py:178`.
      Deprecated; use `asyncio.to_thread(describe, path, vision_cfg)`. *(fixed 2026-08-24 —
      one-line swap. Also added the first tests for `describe_screenshot`, previously entirely
      untested: missing-file error, structured-JSON return, plain-description return — a start
      on the "MCP server has no tests at all" gap below.)*
- [ ] **#13 [low] `discovery.py` is a docstring with no code** — ships in the wheel, importable,
      empty. Delete and move design notes to DECISIONS.md, or implement it.

## Test coverage gaps

- [x] `_describe_anthropic`/`_describe_openai` mocked and tested (2026-08-24, alongside #6).
      `_describe_ollama` still has zero coverage — lower priority, its response shape (plain
      dict) doesn't share the "unpacking assumptions" bug class #6 fixed for the other two.
- [ ] MCP server test coverage: `_resolve_output` (#9) and `describe_screenshot` now covered
      (2026-08-24). Still untested: `capture_url`, `capture_element`, `run_flow_tool`'s
      flow-not-found path, `list_flows`, `_resolve_config`'s env-var fallback.
- [ ] No test covers a flow whose step fails mid-way (#1) or a `describe()` failure mid-run (#5).
- [ ] `cli.py` is untested — Typer's `CliRunner` would cover config-not-found/flow-not-found/
      empty-flows cheaply.
- [ ] All of `tests/test_capture.py` is `@pytest.mark.integration` — `pytest -m 'not integration'`
      currently verifies zero of the capture engine.

## Missing but valuable features (prioritized)

1. **Structured partial results instead of exceptions** from `run_flow_tool` — falls out of
   fixing #1. Single highest-leverage change for agent usability.
2. **Auth/session injection** — `storage_state` file, cookie list, or HTTP basic-auth on the
   context. Almost every internal app a docs tool targets is behind a login.
3. **Viewport/theme variants** — one flow → matrix of captures (`{width=390, name="mobile"}`,
   `{color_scheme="dark"}`, etc.) instead of duplicating the whole flow per variant.
4. **Accessibility snapshot export** (`page.accessibility.snapshot()`) — higher-value output for
   an *agent* consumer than a vision-model guess at a PNG; makes `accessibility_notes` real.
5. **`screenwright validate config.toml`** — pydantic errors with TOML line numbers + a
   selectors-resolve pre-flight pass, so a bad selector fails in <1s instead of 40s into a run.
6. **Retry+backoff+politeness delay** for navigation and vision calls, plus a cost/token report.
7. **Deterministic-capture helpers** — mask selectors (clock/avatar/email), `animations=disabled`
   — pairs with a **screenshot-diff `--check` mode** that fails CI on UI drift. Flagged as the
   most differentiated addition for a docs pipeline specifically.
8. **Parallel flow execution** — `cli.py` runs flows serially with a fresh event loop each; one
   browser + bounded `asyncio.gather` over contexts would cut a multi-flow build several-fold.
9. **PDF export / HAR capture** — lower priority, not core to the MCP+vision differentiator.
10. **`describe_flow` MCP tool** — whole index.md + metadata bundle in one call instead of N
    `describe_screenshot` round-trips.

## Market research (pending — append when the research pass returns)
