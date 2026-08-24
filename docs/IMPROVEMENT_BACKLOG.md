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
      *(fully closed 2026-08-24, later same session: a fresh dependency scan found `anthropic`
      had just released 1.0.0 — a live instance of the exact same unbounded-major-version risk
      that broke CI with `mcp` 2.0.0, sitting unaddressed. Checked structural compatibility
      before pinning (not blindly): `Message.content`/`stop_reason` and `TextBlock.text`/`type`
      all still present in 1.0.0, confirmed by installing it into the dev venv and running the
      full suite for real, not just static inspection. Pinned `anthropic<2.0.0`; also pinned
      `openai<4.0.0` (already silently on 3.x in this project's own installs without issue —
      just formalizing what was already true). Added 2 new tests
      (`test_anthropic_response_shape_matches_our_assumptions`,
      `test_openai_response_shape_matches_our_assumptions`) that check the real installed SDK's
      type shapes directly — the existing mocked describe tests use fake objects and would pass
      even if the real SDK's shape changed, so these are the actual regression guard for a
      future pin bump. `ollama` left unbounded — no 1.0 release yet, and zero real test coverage
      exercises it currently (separate pre-existing gap), so a version bound there has no
      practical enforcement value yet.)*
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
- [x] **#10 [low-medium] No timeouts/viewport control anywhere** — `capture.py:88-94,119-159`.
      No `set_default_timeout`, no per-step override, `wait_until: str` untyped so a typo becomes
      a Playwright error instead of a config validation error. *(the `wait_until` typing half was
      already fixed earlier this session — `NavigateStep.wait_until` is a `Literal[...]`, not a
      bare `str`. Fixed 2026-08-24: `Flow` gains `viewport_width`/`viewport_height` (default
      1280/720, matching Playwright's own Chromium default so unset behavior is unchanged) and
      `timeout_ms` (default 30000, Playwright's own default). `run_flow` passes viewport to
      `browser.new_page()`/`new_context()` and calls `page.set_default_timeout()`;
      `capture_single_url` gained matching `viewport_width`/`viewport_height`/`timeout_ms`
      kwargs. README/API_REFERENCE/wiki updated. Tests: viewport asserted via a dependency-free
      PNG-header dimension reader (no need for an image library); timeout asserted
      behaviorally — a flow with `timeout_ms = 200` against a selector that never appears fails
      in well under 5s instead of the default 30s, proving the value actually took effect rather
      than just existing as an unused config field.)*
- [x] **#11 [low] `save_metadata` annotated `-> Path` but returns `None`** — `output.py:9-18`.
      mypy isn't in CI so unnoticed; fix annotation to `Path | None`. *(fixed 2026-08-24 —
      one-line annotation fix.)*
- [x] **#12 [low] `asyncio.get_event_loop()` inside a coroutine** — `mcp_server.py:178`.
      Deprecated; use `asyncio.to_thread(describe, path, vision_cfg)`. *(fixed 2026-08-24 —
      one-line swap. Also added the first tests for `describe_screenshot`, previously entirely
      untested: missing-file error, structured-JSON return, plain-description return — a start
      on the "MCP server has no tests at all" gap below.)*
- [x] **#13 [low] `discovery.py` is a docstring with no code** — ships in the wheel, importable,
      empty. Delete and move design notes to DECISIONS.md, or implement it. *(fixed 2026-08-24:
      deleted. Its design content (route-mapping problem, possible approaches, suggested CLI
      interface) merged into DECISIONS.md §7, plus two challenges from its TODO that weren't
      already in DECISIONS.md (auth/session injection, which routes to skip). README's roadmap
      row and ARCHITECTURE.md's module table updated to point at DECISIONS.md instead of the
      now-removed file; wiki's Architecture page synced.)*

- [x] **#14 [high, found 2026-08-24 by fresh review, not in the original Opus pass] `_convert_to_mp4`
      failure crashes `run_flow` entirely** — `capture.py`'s video-finalize block called
      `await _convert_to_mp4(final_path)` unguarded when `record_mp4 = true`. A missing `ffmpeg`
      (the exact case `FfmpegNotFoundError`'s own message anticipates) or a failed conversion
      propagated out of `run_flow` as an unhandled exception — both `cli.py`'s `_process_flow`
      and `mcp_server.py`'s `run_flow_tool` call `run_flow` with no try/except, so this crashed
      the whole CLI run or MCP tool call, losing every capture and the `.webm` that had already
      succeeded. This is the same class of bug as finding #1 (browser/context setup, the step
      loop) but for the one finalize-block call that was never brought under the "always return
      a `FlowResult`, never raise" contract established when #1 was fixed. *(fixed 2026-08-24:
      wrapped the `_convert_to_mp4` call in try/except; a failure is appended to `result.error`
      (chained with `;` if a step already failed) instead of raising — `result.video_path`,
      `result.captures`, and everything else already succeeded stay intact. 1 new test
      (`test_run_flow_reports_missing_ffmpeg_instead_of_raising`), monkeypatching
      `shutil.which` to simulate a missing ffmpeg deterministically rather than depending on the
      host machine's actual ffmpeg install.)*
- [x] **#15 [medium, CodeQL-flagged, not in the original Opus pass] GitHub Actions workflow
      hardening** — GitHub's default CodeQL Actions analysis (enabled once the repo went public)
      flagged three findings: (1) `ci.yml`'s `test` job had no explicit `permissions` block, so
      it ran with the repo's default (often read-write) `GITHUB_TOKEN` scope instead of the
      minimum it actually needs; (2) `publish.yml`'s `build` job had the same gap (its `publish`
      job already set explicit `id-token: write`, so it wasn't flagged); (3) `publish.yml`'s
      `pypa/gh-action-pypi-publish@release/v1` step referenced a floating branch tag rather than
      a pinned commit SHA — a supply-chain risk, since a compromised or rewritten tag would run
      untrusted code with this job's PyPI publish credentials. *(fixed 2026-08-24: added
      `permissions: contents: read` at `ci.yml`'s workflow level and to `publish.yml`'s `build`
      job — matching the least-privilege pattern `security.yml` already used; pinned the PyPI
      publish step to `release/v1`'s current commit SHA
      (`dc37677b2e1c63e2034f94d8a5b11f265b73ba33`, tag `v1.14.2`) with a comment naming the tag
      it corresponds to, so a future intentional upgrade is a one-line diff. No Python code
      changed; verified by re-running `pytest`/`ruff check`/`ruff format --check` to confirm the
      unrelated fix didn't regress anything, and by inspecting the YAML directly since GitHub
      Actions workflows aren't part of the pytest suite.)*

- [x] **#16 [high, found 2026-08-24 by fresh review, not in the original Opus pass]
      `capture_single_url` leaks the browser process on any setup/navigation/capture failure** —
      `capture.py:155-174`. `await browser.close()` was the literal last line of the function
      body, not in a try/finally — a bad `selector` (raised by `_capture_page_or_element`), a
      navigation failure after `_goto_with_retry` exhausts its retries, or any `new_page`
      failure all skipped it, leaking the launched Chromium process. This is the same class of
      bug as finding #1, but for `capture_single_url` — the function behind the MCP
      `capture_url`/`capture_element` tools — which never got the same try/finally treatment
      `run_flow` did. Real risk on the MCP surface specifically: an agent plausibly retries
      `capture_url`/`capture_element` with a different selector after a "Selector not found"
      error, leaking one more browser per failed attempt — over a long agent session this is a
      genuine resource-exhaustion path on whatever host runs the MCP server. *(fixed 2026-08-24:
      wrapped the body in try/finally, matching `run_flow`'s existing pattern exactly — no
      behavior change to what gets raised or returned on success. 1 new test
      (`test_capture_single_url_closes_browser_even_if_setup_fails`), using a fake
      `async_playwright`/browser/chromium trio (monkeypatched) rather than a real browser, so
      it's deterministic and doesn't depend on triggering a real Playwright failure.)*

- [x] **#17 [high, found 2026-08-24 by fresh review, not in the original Opus pass]
      `describe_flow`'s `flow_name` had no path-traversal validation** — `mcp_server.py`'s
      `describe_flow` built `flow_dir = out_root / flow_name` directly, with no call to
      `validate_safe_name` — the same protection `capture_url`/`capture_element`'s `name` param
      already got under finding #2. `flow_name` is agent-supplied on this MCP surface, same
      threat model as #2: an LLM acting on untrusted page content could pass
      `flow_name="../../../../home/user/.config/some-app"` and `describe_flow` would read
      `index.md`/`*.png`/`*.json` from that arbitrary directory and return their contents to the
      calling agent — an information-disclosure path that `run_flow_tool`'s `flow_name` doesn't
      share (it's only a dict-lookup key there, never a path segment). *(fixed 2026-08-24: added
      `validate_safe_name(flow_name)` at the top of `describe_flow`, before any path
      construction — rejects, doesn't sanitize, matching every other name-validation site in
      this codebase. 5 new parametrized tests
      (`test_describe_flow_rejects_path_traversal_flow_name`), reusing the same traversal
      payloads finding #2's own tests use. `docs/MCP_TOOLS.md` and the wiki's
      MCP-Tools-Reference page updated to document the constraint.)*

- [x] **#18 [high, found 2026-08-24 by fresh review, not in the original Opus pass] Video/HAR
      finalize block could still raise past the mp4-conversion fix** — `capture.py`'s finalize
      block wraps `_convert_to_mp4` in try/except (finding #14), but the surrounding
      `page.close()`, `context.close()`, `video.path()`, and `raw_path.replace(final_path)`
      calls were still unguarded. A full disk, a page that crashed mid-flow, or a Playwright
      internal error on close would still propagate out of `run_flow` unhandled — the same class
      of bug as #14 and #16, but for the rest of this one block rather than the finalize call
      that got fixed first. *(fixed 2026-08-24: wrapped the whole block (not just the mp4-
      conversion call) in an outer try/except, appending `Failed to finalize video/HAR: ...` to
      `result.error` — chained with any earlier step/mp4 error rather than replacing it. This
      completes the "never raise" contract for every path through `run_flow`'s finalize logic.
      1 new test (`test_run_flow_reports_video_finalize_failure_instead_of_raising`),
      monkeypatching `Path.replace` to raise deterministically rather than depending on an
      actual disk-full or crashed-page condition.)*

- [x] **#19 [medium, found 2026-08-24 by fresh review, not in the original Opus pass] Partial
      flow failures were invisible in the generated docs themselves** — `output.py`'s
      `_flow_index_md`/`_root_readme_md` never rendered `FlowResult.error`. Every crash-on-
      error-path fix this session (#1, #14, #16, #18) guarantees a mid-flow failure returns a
      `FlowResult` with `.error` set instead of raising, but nothing ever surfaced that field
      into the docs a `screenwright run` actually produces — a partial run's `index.md` and root
      `README.md` looked identical to a fully successful one, with the failure visible only in
      ephemeral CLI console output that's gone the moment the terminal scrolls. For a
      documentation tool specifically, that's a real gap: anyone opening the generated docs
      later (or an MCP agent calling `describe_flow`, which reads `index.md`) had no way to know
      a flow stopped early. *(fixed 2026-08-24: `_flow_index_md` prepends a
      `⚠️ Flow stopped early: {error}` banner above the capture table when `.error` is set
      (escaped through the existing `_escape_markdown_cell`, since `.error` can embed a selector
      string or other config-derived text); `_root_readme_md` gained a `✅`/`⚠️ Partial` Status
      column. 3 new tests
      (`test_write_root_readme_flags_partial_flow_status`,
      `test_write_flow_output_shows_error_banner_when_flow_stopped_early`,
      `test_write_flow_output_omits_error_banner_on_success`); 1 existing test
      (`test_write_root_readme_lists_all_flows`) updated for the new column format.
      README's Output Format section updated.)*

- [x] **#20 [medium, found 2026-08-24 by fresh review, not in the original Opus pass]
      `ScreenwrightConfig` never rejected duplicate flow names** — `config.py`. Every flow's
      output path is derived from its name (`output_dir / flow.name`), so two flows sharing a
      name silently wrote to the same directory: one overwrites the other's captures/index.md,
      `get_flow()` only ever returns the first match (the second flow's steps still run, just
      unreachable by name afterward), and — worse — under `--concurrency > 1` both flows record
      video/HAR to the same directory concurrently, which can corrupt either file. A copy-paste
      typo duplicating a `[[flows]]` block and forgetting to rename it is the realistic way to
      trigger this. *(fixed 2026-08-24: added a `model_validator(mode="after")` on
      `ScreenwrightConfig` that rejects — doesn't silently dedupe — any duplicate flow name,
      naming the duplicate(s) in the error. Matches the reject-don't-sanitize philosophy
      `validate_safe_name` already established for names elsewhere in this codebase, and fits
      the same "fail fast with a clear error, not a confusing runtime result" pitch `validate`
      already makes for schema violations. 4 new tests (config-load rejection, direct
      `ScreenwrightConfig` construction rejection/acceptance). README's `validate` description
      updated to list this alongside the other things it now catches.)*

- [x] **#21 [medium, found 2026-08-24 by fresh review, not in the original Opus pass] Same
      duplicate-name failure mode existed one and two levels below flow names (#20)** —
      `CaptureStep.variants` sharing a name both produce `{name}-{variant.name}.png`; two
      `capture` steps in the same `Flow` sharing a name both write `{flow_dir}/{name}.png`. Both
      silently overwrite each other's output, same failure mode as #20, just at a finer grain —
      a copy-pasted `capture` step or `variants` entry with the rename forgotten is at least as
      realistic a mistake as a copy-pasted `[[flows]]` block. *(fixed 2026-08-24: added the same
      `model_validator(mode="after")` pattern to `CaptureStep` (rejects duplicate variant names)
      and `Flow` (rejects duplicate capture-step names), both naming the duplicate(s) in the
      error. 5 new tests spanning direct model construction and `load_config()`. README's
      `validate` description updated.)*

- [x] **#22 [medium, found 2026-08-24 by fresh review, not in the original Opus pass] Variant
      `color_scheme` could leak into a later variant in the same step** — `capture.py`'s variant
      loop only called `page.emulate_media(color_scheme=...)` when a variant explicitly set
      `color_scheme`; when unset, the call was skipped entirely rather than resolving to
      `"light"`, which `Variant`'s own docstring already documents as the guaranteed fallback. A
      `dark` variant followed by a variant that doesn't set `color_scheme` rendered that later
      variant still in dark mode — the state from the earlier variant, not the documented
      default. The existing post-step restore (added under an earlier fix) only resets state
      *after* the whole variants loop finishes; it doesn't help variant-to-variant leakage within
      the same step, which is a different bug at a finer grain. *(fixed 2026-08-24: always
      resolve `color_scheme` explicitly per variant
      (`variant.color_scheme if variant.color_scheme is not None else "light"`), mirroring how
      viewport width/height already resolve per-variant with a flow-default fallback instead of
      being conditionally skipped. 1 new test
      (`test_run_flow_variant_color_scheme_does_not_leak_between_variants`), spying on the real
      `Page.emulate_media` to assert the actual call sequence (`["dark", "light", "light"]` —
      the leak-preventing "light" for the second variant, then the existing post-step restore's
      own "light") rather than a fake object graph. README's Capture Variants section clarified
      that the per-field fallback applies fresh to each variant, not once at the end of the
      step.)*

- [x] **#23 [low-medium, found 2026-08-24 by fresh review, not in the original Opus pass]
      `docs/API_REFERENCE.md` had gone stale relative to ~10 commits' worth of real API
      changes this session** — it never got a single edit across the whole session's fixes,
      while `README.md`/`docs/ARCHITECTURE.md`/the wiki were kept in sync per-commit. Missing:
      `capture_single_url`'s `timeout_ms`/`viewport_width`/`viewport_height`/`animations`
      params (added earlier this session, before this backlog file's tracking began);
      `FlowResult.failed_step_index`/`.error` entirely undocumented, despite being the central
      contract every crash-on-error-path fix this session relies on; no mention that `run_flow`
      never raises for a step/setup/finalize failure (the exact guarantee findings #1, #14,
      #16, #18 established); no mention of the duplicate flow/capture/variant name validation
      (#20, #21) or the partial-flow-failure docs banner/Status column (#19). For a Python
      library reference specifically, an out-of-sync contract description is worse than no
      documentation — it actively misleads a caller into wrapping `run_flow` in try/except it
      doesn't need, or missing that `.error` is the thing to check. *(fixed 2026-08-24: synced
      every section against the actual current source — `capture.py`, `output.py`,
      `config.py` — rather than assuming prior doc text was still accurate. Wiki's
      Python-API-Reference page synced to match. No code changed; verified via a full
      `pytest`/`ruff check`/`ruff format --check` pass to confirm the docs-only change didn't
      regress anything.)*

- [x] **#24 [low, found 2026-08-24 by fresh review, not in the original Opus pass]
      `describe_screenshot`'s `provider` param was typed `str`, not the `Literal` it actually
      validates against** — `mcp_server.py`. `VisionConfig.provider` is
      `Literal["anthropic", "ollama", "openai"]`, but the MCP tool signature took a bare `str`
      and cast it into `VisionConfig` with a `# type: ignore[arg-type]`. FastMCP derives each
      tool's exposed schema from its Python type hints, so a real MCP client saw `provider` as
      an unconstrained string with no indication of the three valid values — worse
      discoverability than every other enum-like param in this codebase (`NavigateStep.wait_until`,
      `CaptureStep.animations`, `Variant.color_scheme` are all already `Literal`). *(fixed
      2026-08-24: retyped `provider: Literal["anthropic", "ollama", "openai"] = "anthropic"`,
      matching `VisionConfig.provider` exactly and dropping the now-unneeded type-ignore. 1 new
      test confirming an out-of-schema value still gets a clear Pydantic `ValidationError` at
      the `VisionConfig` layer — the fallback for a client that ignores the schema, since Python
      itself doesn't enforce type hints on a direct call. `docs/MCP_TOOLS.md` and the wiki's
      MCP-Tools-Reference page updated.)*

## Test coverage gaps

- [x] `_describe_anthropic`/`_describe_openai` mocked and tested (2026-08-24, alongside #6).
      `_describe_ollama` closed 2026-08-24 (later session pass): turned out `response["message"]
      ["content"]` isn't plain-dict indexing as originally assumed — `ollama.chat()` returns a
      `ChatResponse`/`Message` pair (Pydantic models with `__getitem__` for backward-compat dict
      access), verified directly against the installed SDK (0.6.2) before writing the test, not
      assumed. 3 new tests: return-value + call-argument mocked tests, plus a
      `test_ollama_response_shape_matches_our_assumptions` structural guard matching the pattern
      already used for anthropic/openai. Also fixed a related gap while here: `pyproject.toml`'s
      `dev` extra only pulled in `screenwright[anthropic,openai]`, not `ollama` — these new
      tests would have passed locally (ollama was installed as a leftover from earlier session
      work) but failed in a fresh CI install. Switched `dev` to depend on `screenwright[vision]`
      (all three providers) instead of listing two of three individually.
      **This closes the last item in the "Test coverage gaps" section — fully done.**
- [x] MCP server test coverage — `_resolve_output` (#9), `describe_screenshot`, `capture_url`
      (incl. its path-traversal rejection through the real tool, not just `_resolve_capture_path`
      directly), `capture_element`, `list_flows` (with/without a config), `_resolve_config`'s
      explicit-path/env-var/neither precedence, and `run_flow_tool`'s flow-not-found error path
      (asserts the error lists available flow names, so an agent can self-correct on the next
      call). All covered as of 2026-08-24 — MCP server test-coverage gap fully closed.
- [x] No test covers a flow whose step fails mid-way (#1) or a `describe()` failure mid-run (#5).
      *(this was already stale by the time it was next reviewed — both landed alongside the #1/#5
      fixes themselves: `test_run_flow_step_failure_returns_partial_result_not_exception`,
      `test_run_flow_with_recording_finalizes_video_on_step_failure` in `tests/test_capture.py`,
      and `test_run_continues_past_a_single_describe_failure` in `tests/test_cli.py`.)*
- [x] `cli.py`: `run`'s config-not-found/flow-not-found/empty-flows paths and `validate`'s
      success/error paths now covered (2026-08-24, `tests/test_cli_validate.py`).
      *(fully closed 2026-08-24, later pass: `run --output` override was already covered by
      `test_run_completes_all_flows_at_various_concurrency` and the `--check` tests, both of
      which pass `--output`; `flows`' happy path was the one real gap — closed with
      `test_flows_lists_each_flow_with_step_and_capture_counts` and
      `test_flows_reports_no_flows_defined` in `tests/test_cli_validate.py`, both
      non-integration-marked since `flows` never launches a browser.)*
- [ ] All of `tests/test_capture.py` is `@pytest.mark.integration` (still true — capture always
      needs a browser). `tests/test_cli_validate.py` is the first non-integration-marked test
      file (2026-08-24) — config validation never touches a browser, so
      `pytest -m 'not integration'` now verifies something beyond pure-unit helpers.

## Missing but valuable features (prioritized)

1. **Structured partial results instead of exceptions** from `run_flow_tool` *(shipped
   2026-08-24, alongside finding #1's fix)* — `run_flow_tool` returns
   `{captures, video_path, video_mp4_path, error, failed_step_index}` instead of raising or
   returning a bare path list; a mid-flow step failure still returns everything captured before
   it, not just an exception. Covered by `test_run_flow_tool_returns_partial_result_dict_on_step_failure`
   in `tests/test_mcp_server.py`. This item was left unchecked after the #1 fix landed even
   though it was the same commit — noticed on a later backlog review pass, not a separate fix.
2. **Auth/session injection** *(shipped 2026-08-24)* — `Flow.storage_state` loads a Playwright
   `storage_state` JSON file (cookies + localStorage) before the flow runs, via
   `browser.new_page(storage_state=...)`/`new_context(storage_state=...)`. NOT implemented:
   inline cookie list or HTTP basic-auth directly in TOML — `storage_state` covers the common
   case (capture a session once via `playwright codegen --save-storage=...`, reuse it) and is
   Playwright's own standard mechanism, so this is likely sufficient; revisit only if a real
   need for inline cookies/basic-auth surfaces. Also fixed while implementing this: browser/
   context/page *setup* (not just the step loop) is now wrapped in the same try/except as steps
   — previously a failure there (which storage_state loading is a new, realistic way to trigger:
   a missing/malformed file) would have propagated out of `run_flow` as an unhandled exception,
   contradicting the "always return a `FlowResult`, never raise" contract from finding #1. 3 new
   tests (valid/missing/malformed storage_state). README/API_REFERENCE/ARCHITECTURE/wiki updated.
3. **Viewport/theme variants** *(shipped 2026-08-24, deferred twice before this — see below)* —
   scoped per `capture` step, not per flow: `CaptureStep.variants` (list of `Variant`) captures
   that one step once per viewport/color-scheme combination instead of once, producing
   `{name}-{variant.name}.png`. Implementation is deliberately the *simple* design that avoids
   the risk the earlier deferrals were worried about — instead of spinning up a fresh
   browser/context per variant (which would have touched the well-tested video-recording and
   setup-error-handling code that path shares), it calls `page.set_viewport_size()`/
   `page.emulate_media()` on the *existing* page before each variant's capture, all within the
   existing `CaptureStep` branch. Zero changes to browser/context lifecycle. One real gotcha
   found while verifying this against the installed Playwright (1.59) before writing any code:
   `page.emulate_media(color_scheme=None)` is a no-op, not a reset — restoring the flow's
   default after a variant requires an explicit `"light"`. Composes with `accessibility_snapshot`/
   `pdf` on the same step (both apply per variant too). 8 new tests, including one asserting zero
   behavior change when `variants` is unset (the default for every flow written before this
   existed). README/API_REFERENCE/ARCHITECTURE/wiki updated.
4. **Accessibility snapshot export** *(shipped 2026-08-24)* — `page.accessibility.snapshot()`
   was already removed from the installed Playwright version (1.59) by the time this was
   implemented; used the current API, `page.aria_snapshot()` / `Locator.aria_snapshot()`,
   instead. New `CaptureStep.accessibility_snapshot` (bool) writes `{name}.aria.yaml` alongside
   the PNG, always whole-page — `aria_snapshot()` isn't available on the `ElementHandle` this
   step's selector-scoped screenshot path uses, only on `Page`/`Locator`. Linked from the flow's
   `index.md` next to the image ref. 5 new tests. README/API_REFERENCE/ARCHITECTURE/wiki
   updated. This did NOT make `accessibility_notes` in `ScreenshotMetadata` "real" as originally
   framed — that field is still a separate vision-model guess; wiring the aria snapshot into the
   vision prompt as grounding context is a distinct, unstarted follow-up.
5. **`screenwright validate config.toml`** *(partially shipped 2026-08-24)* — implemented the
   schema-validation half: `validate` catches TOML syntax errors and Pydantic schema violations
   in well under a second, with clean "field.path: message" output (no raw traceback), shared
   via a new `_load_config_or_exit()` helper that `run`/`flows` now also use instead of letting
   `load_config()` raise unhandled. NOT implemented: pydantic errors annotated with TOML line
   numbers (would need a source-span-tracking TOML parser like `tomlkit` instead of stdlib
   `tomllib` — a real new dependency, deferred) and the selectors-resolve pre-flight pass (needs
   an actual browser navigation per flow, which conflicts with `validate`'s current no-network/
   offline/no-side-effects design goal — would need to be an opt-in flag, e.g. `--live`, not
   `validate`'s default behavior, if added). 6 new tests in `tests/test_cli_validate.py` — first
   file in the test suite not integration-marked, since config validation never touches a
   browser (partial progress on the `pytest -m 'not integration'` coverage gap below).
6. **Retry+backoff for navigation** *(shipped 2026-08-24)* — `capture.py` gained
   `_goto_with_retry`/`_is_transient_navigation_error`, mirroring `vision.py`'s existing
   `_with_retry`/`_is_transient` pattern (already shipped for vision calls under finding #5)
   but async, since `page.goto()` is async and vision's SDK calls are synchronous. Retries up to
   2x with the same 1s/2s exponential backoff, only on `playwright.async_api.TimeoutError` or a
   `net::ERR_*` error message — a 404 or bad selector isn't retried, since retrying a permanent
   failure just delays reporting it. Applied to both `run_flow`'s `NavigateStep` handling and
   `capture_single_url`. 6 new unit tests (transient-detection + retry-then-succeed/give-up/
   don't-retry, using a fake `Page` object rather than a real browser). NOT done: a
   politeness/rate-limit delay between requests, and a cost/token usage report for vision calls
   — both separate, lower-priority scope; split out of this item since "retry" and "politeness
   delay" solve different problems (resilience vs. not hammering a target site/API).
7. **Deterministic-capture helpers** *(shipped 2026-08-24)* — `CaptureStep.animations` (default
   `"disabled"`, a deliberate departure from Playwright's own `"allow"` default) and
   `CaptureStep.mask`/`mask_color` (fill selectors with a solid color before capturing).
   Verified directly against the installed Playwright before writing code: masking a
   non-matching selector is a silent no-op (unlike `selector`, which raises), so an optional
   masking target doesn't have to exist on every page a flow runs against. 8 new tests.
   README/API_REFERENCE/ARCHITECTURE/wiki updated. The **screenshot-diff `--check` mode** this
   was originally paired with shipped separately below (item 10).
8. **Parallel flow execution** *(shipped 2026-08-24)* — new `screenwright run --concurrency N`
   (default 1, i.e. today's sequential behavior unless opted into). Implementation differs from
   the original framing ("one browser + bounded asyncio.gather over contexts") — kept each
   flow's own independent `run_flow()` browser instance (unchanged) and instead restructured
   `cli.py run` from "one `asyncio.run()` call per flow in a sync loop" to a single
   `asyncio.run()` wrapping an `asyncio.Semaphore`-bounded `asyncio.gather` over all flows;
   `describe()` (synchronous, vendor SDK clients) now runs via `asyncio.to_thread()` so it
   doesn't block other flows under concurrency > 1. The per-flow Rich progress task is created
   only after the semaphore is acquired, not upfront for every flow, so `--concurrency 1`'s
   progress display is pixel-for-pixel identical to before this option existed — verified with a
   parametrized test running the same 2-flow config at concurrency 1 and 2. 3 new tests.
   README/ARCHITECTURE/wiki updated.
9. **PDF export** / **HAR capture** — both shipped 2026-08-24. `CaptureStep.pdf` calls
   `page.pdf()` — Chromium-only, whole-page like `accessibility_snapshot` (not scoped to
   `selector`, same underlying reason: not available on the `ElementHandle` this step's
   selector path uses). 5 new tests. `Flow.har` records network traffic to `{flow_name}.har`,
   flow-scoped like `record` (context/page-level recorder, can't toggle mid-flow). Implementing
   HAR surfaced a real gap verified directly against the installed Playwright before writing
   code: `.har` (like `.webm`) only flushes on explicit page/context close, and the non-`record`
   path never closed `page` explicitly before this — HAR would have silently produced an empty
   file in that case. Broadened the finalize block's guard from
   `context is not None and page is not None` to just `page is not None` to fix it — harmless
   when neither video nor HAR is active. 5 new tests including HAR+video together.
   README/API_REFERENCE/ARCHITECTURE/wiki updated for both.
10. **`describe_flow` MCP tool** *(shipped 2026-08-24)* — whole index.md + metadata bundle in
    one call instead of N `describe_screenshot` round-trips. Pure filesystem read (no
    Playwright, no changes to the core capture path) — reads what `run_flow_tool` +
    `write_flow_output` already wrote, doesn't run anything. Returns
    `{flow_name, index_md, captures: [{name, path, metadata}]}`; a capture with no `.json`
    sidecar gets `metadata: null` rather than being dropped. 2 new tests. README, MCP_TOOLS.md,
    and wiki updated.
11. **Screenshot diff `--check` mode** *(shipped 2026-08-24)* — `screenwright run --check` exits
    1 and lists changed `{flow_name}/{capture_name}` pairs if any PNG's SHA256 differs from the
    previous run in the same output directory (or is new); exits 0 otherwise. Scoped down from
    the originally-envisioned perceptual/pixel-diff-with-baseline-store feature to an exact-byte
    diff living entirely in `cli.py` — `run_flow`/`capture.py` untouched, hashing skipped
    entirely when `--check` isn't passed (zero overhead for the common case). Deliberately pairs
    with item 7's `animations`/`mask` determinism work — `--check` has no pixel tolerance, so
    residual non-determinism should be fixed there, not worked around here. 4 new tests
    (first-run-all-changed, identical-rerun-no-changes, content-change-detected,
    without-`--check`-no-diff-report). README/ARCHITECTURE/wiki updated.

## Market research (pending — append when the research pass returns)
