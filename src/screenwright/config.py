from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, field_validator

_DEFAULT_DESCRIBE_PROMPT = "Describe this UI screenshot for documentation purposes."

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


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


class CaptureStep(BaseModel):
    action: Literal["capture"]
    name: str
    selector: str | None = None

    _validate_name = field_validator("name")(validate_safe_name)


class FillStep(BaseModel):
    action: Literal["fill"]
    selector: str
    value: str


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

    _validate_name = field_validator("name")(validate_safe_name)


class ScreenwrightConfig(BaseModel):
    output_dir: str = "docs/screenshots"
    base_url: str = ""
    vision_describe: bool = True
    vision: VisionConfig = Field(default_factory=VisionConfig)
    flows: list[Flow] = []

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
