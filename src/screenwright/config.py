from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, field_validator, model_validator

_DEFAULT_DESCRIBE_PROMPT = "Describe this UI screenshot for documentation purposes."

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
ENV_REF_RE = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")


def validate_safe_name(name: str) -> str:
    """Reject anything usable for path traversal or an absolute path.

    Flow/capture names are used directly to build filesystem paths
    (``flow_dir / f"{name}.png"``). On the MCP surface these names can come
    from an LLM acting on untrusted page content, so this validates rather
    than silently sanitizes — a rejected name is a clear error, a silently
    rewritten one is a surprise.
    """
    if not _SAFE_NAME_RE.fullmatch(name) or ".." in name or name in (".", ".."):
        raise ValueError(
            f"Invalid name {name!r}: must match {_SAFE_NAME_RE.pattern} and not be a "
            "path-traversal segment."
        )
    return name


class VisionConfig(BaseModel):
    provider: Literal["anthropic", "ollama", "openai"] = "anthropic"
    model: str = "claude-haiku-4-5"
    structured_metadata: bool = True
    prompt: str = _DEFAULT_DESCRIBE_PROMPT


class NavigateStep(BaseModel):
    action: Literal["navigate"]
    url: str
    wait_until: Literal["load", "domcontentloaded", "networkidle", "commit"] = "load"


class Variant(BaseModel):
    """One entry in a `capture` step's `variants` matrix.

    Any field left unset falls back to the flow's own default
    (`Flow.viewport_width`/`viewport_height` for viewport; Chromium's
    default "light" for color scheme) — a variant only needs to specify
    what it's actually varying, e.g. `{name = "mobile", viewport_width =
    390, viewport_height = 844}` or `{name = "dark", color_scheme = "dark"}`.
    """

    name: str
    viewport_width: int | None = None
    viewport_height: int | None = None
    color_scheme: Literal["light", "dark", "no-preference"] | None = None

    _validate_name = field_validator("name")(validate_safe_name)


class CaptureStep(BaseModel):
    action: Literal["capture"]
    name: str
    selector: str | None = None
    accessibility_snapshot: bool = False
    """When true, also write the page's accessibility tree (Playwright's
    `aria_snapshot()`) to `{name}.aria.yaml` alongside the PNG. This is
    always for the whole page, not scoped to `selector` — Playwright's
    aria_snapshot is a Locator/Page method, not available on the
    ElementHandle this step uses for element-scoped screenshots. Useful for
    an agent consumer: the semantic tree is cheaper and more reliable to
    reason about than a vision model's guess at a PNG.
    """
    pdf: bool = False
    """When true, also save the whole page as `{name}.pdf` alongside the PNG
    (Playwright's `page.pdf()` — Chromium-only, whole-page like
    `accessibility_snapshot`, not scoped to `selector`). Useful for
    print-formatted documentation output or archiving a page's full
    content beyond the viewport, not just what a screenshot shows.
    """
    variants: list[Variant] = Field(default_factory=list)
    """Capture this step once per variant instead of once — e.g. mobile +
    desktop, or light + dark — instead of duplicating the whole flow per
    combination. Each variant produces `{name}-{variant.name}.png` (plus
    `.aria.yaml`/`.pdf` too, if this step also sets `accessibility_snapshot`/
    `pdf`). Viewport/color-scheme changes made for variants are restored to
    the flow's defaults after this step finishes, so later steps in the
    same flow aren't left running under a variant's settings. An empty list
    (the default) captures once, exactly as before this field existed.
    """
    animations: Literal["disabled", "allow"] = "disabled"
    """Whether CSS animations/transitions/infinite-animations run during the
    screenshot (Playwright's own `animations` screenshot option). Defaults
    to "disabled" — a deliberate departure from Playwright's own default of
    "allow" — because a documentation screenshot tool should default to
    deterministic, reproducible output; a mid-animation frame is rarely
    what you actually want captured, and it's the single biggest source of
    unnecessary diff-noise on re-runs. Set to "allow" for the rare case
    where the animation itself is what's being documented.
    """
    mask: list[str] = Field(default_factory=list)
    """CSS selectors to mask (filled with a solid color) before capturing —
    e.g. a live clock, an avatar, an email address — so a screenshot of the
    same page produces the same pixels on every run instead of differing
    only in dynamic content that isn't the point of the documentation.
    """
    mask_color: str | None = None
    """Override color for masked elements. Playwright's own default is
    pink (`#FF00FF`), chosen specifically to be unmissable — don't switch
    to something that could pass as a real UI color unless you have a
    reason to.
    """

    _validate_name = field_validator("name")(validate_safe_name)


class FillStep(BaseModel):
    action: Literal["fill"]
    selector: str
    value: str
    secret: bool = False
    """If true, `value` must be an ${ENV_VAR} reference, not a literal — this
    is a load-time nudge against committing plaintext credentials next to
    the flow that uses them. The value is still resolved and typed into the
    page like any other fill (Screenwright doesn't intercept what the vision
    model then sees in a post-fill screenshot — mask the field in the UI
    itself, or skip capturing that step, if the screenshot must not show it).
    """

    @model_validator(mode="after")
    def _secret_requires_env_ref(self) -> "FillStep":
        if self.secret and not ENV_REF_RE.fullmatch(self.value):
            raise ValueError(
                "secret = true requires value to be an ${ENV_VAR} reference, not a literal string."
            )
        return self


class ClickStep(BaseModel):
    action: Literal["click"]
    selector: str


class WaitStep(BaseModel):
    action: Literal["wait"]
    ms: int


class HoverStep(BaseModel):
    action: Literal["hover"]
    selector: str


class PressStep(BaseModel):
    action: Literal["press"]
    selector: str
    key: str


class CheckStep(BaseModel):
    action: Literal["check"]
    selector: str
    checked: bool = True


class SelectStep(BaseModel):
    action: Literal["select"]
    selector: str
    value: str


Step = Annotated[
    Union[
        NavigateStep,
        CaptureStep,
        FillStep,
        ClickStep,
        WaitStep,
        HoverStep,
        PressStep,
        CheckStep,
        SelectStep,
    ],
    Field(discriminator="action"),
]


class Flow(BaseModel):
    name: str
    steps: list[Step] = []
    record: bool = False
    record_width: int = 1280
    record_height: int = 720
    record_mp4: bool = False
    viewport_width: int = 1280
    viewport_height: int = 720
    timeout_ms: int = 30000
    storage_state: str | None = None
    """Path to a Playwright storage_state JSON file (cookies + localStorage) to
    load before the flow's steps run — the standard way to capture an
    already-authenticated session instead of scripting a login flow with
    `fill`/`click` steps every run. Generate one with Playwright's own
    tooling (e.g. `playwright codegen --save-storage=state.json` after
    logging in manually) or `context.storage_state(path=...)` in a setup
    script. Not validated at config-load time (this only touches the
    filesystem when the flow actually runs); a missing/invalid file
    surfaces as a normal Playwright error when the browser context opens.
    """
    har: bool = False
    """When true, record the flow's network traffic to `{flow_name}.har`
    (Playwright's own HAR format) — every request/response, timing, and
    header for the whole flow. Useful for debugging why a capture rendered
    blank or wrong (a failed API call, a slow resource, a redirect loop)
    without needing to reproduce the issue interactively. Flow-scoped like
    `record`, for the same reason: it's a context/page-level recorder that
    only flushes to disk when the page closes, so it can't be toggled
    mid-flow the way a `capture` step's own options can.
    """

    _validate_name = field_validator("name")(validate_safe_name)


class ScreenwrightConfig(BaseModel):
    output_dir: str = "docs/screenshots"
    base_url: str = ""
    vision_describe: bool = True
    vision: VisionConfig = Field(default_factory=VisionConfig)
    flows: list[Flow] = []

    @model_validator(mode="after")
    def _validate_unique_flow_names(self) -> "ScreenwrightConfig":
        """Reject duplicate flow names instead of silently corrupting output.

        Every flow's output path is derived from its name
        (``output_dir / flow.name``), so two flows sharing a name write to
        the exact same directory — one flow's captures/index.md silently
        overwrite the other's, and `get_flow()` can only ever return the
        first match. Under `--concurrency > 1` this is worse than silent:
        both flows record video/HAR to the same directory concurrently,
        which can corrupt either file. A copy-paste typo in TOML is the
        realistic way to trigger this, so it's caught here rather than
        producing confusing output.
        """
        seen: set[str] = set()
        duplicates: set[str] = set()
        for flow in self.flows:
            if flow.name in seen:
                duplicates.add(flow.name)
            seen.add(flow.name)
        if duplicates:
            raise ValueError(
                f"Duplicate flow name(s): {', '.join(sorted(duplicates))}. "
                "Each flow must have a unique name — output paths are derived from it."
            )
        return self

    def get_flow(self, name: str) -> Flow | None:
        for flow in self.flows:
            if flow.name == name:
                return flow
        return None

    def flow_names(self) -> list[str]:
        return [f.name for f in self.flows]


def load_config(path: str | Path) -> ScreenwrightConfig:
    path = Path(path)
    with path.open("rb") as f:
        raw = tomllib.load(f)

    section = raw.get("screenwright", {})
    section["flows"] = raw.get("flows", [])

    vision_raw = raw.get("vision", {})
    if vision_raw:
        section["vision"] = vision_raw

    return ScreenwrightConfig.model_validate(section)
