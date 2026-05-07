from __future__ import annotations

import textwrap
from pathlib import Path

from screenwright.config import (
    CaptureStep,
    ClickStep,
    FillStep,
    NavigateStep,
    ScreenwrightConfig,
    VisionConfig,
    WaitStep,
    load_config,
)


def write_toml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "config.toml"
    p.write_text(textwrap.dedent(content))
    return p


def test_defaults():
    cfg = ScreenwrightConfig()
    assert cfg.output_dir == "docs/screenshots"
    assert cfg.vision_describe is True
    assert cfg.vision.provider == "anthropic"
    assert cfg.vision.model == "claude-haiku-4-5"
    assert cfg.vision.structured_metadata is True
    assert cfg.flows == []


def test_load_minimal(tmp_path):
    p = write_toml(
        tmp_path,
        """
        [screenwright]
        base_url = "https://example.com"
        """,
    )
    cfg = load_config(p)
    assert cfg.base_url == "https://example.com"
    assert cfg.flows == []


def test_load_vision_section(tmp_path):
    p = write_toml(
        tmp_path,
        """
        [screenwright]
        base_url = "https://example.com"

        [vision]
        provider = "ollama"
        model = "moondream"
        structured_metadata = false
        prompt = "Custom prompt."
        """,
    )
    cfg = load_config(p)
    assert cfg.vision.provider == "ollama"
    assert cfg.vision.model == "moondream"
    assert cfg.vision.structured_metadata is False
    assert cfg.vision.prompt == "Custom prompt."


def test_load_flow_with_steps(tmp_path):
    p = write_toml(
        tmp_path,
        """
        [screenwright]
        base_url = "https://example.com"

        [[flows]]
        name = "login"

          [[flows.steps]]
          action = "navigate"
          url = "/login"

          [[flows.steps]]
          action = "capture"
          name = "login-empty"
          selector = "form"

          [[flows.steps]]
          action = "fill"
          selector = "#email"
          value = "test@example.com"

          [[flows.steps]]
          action = "click"
          selector = "button[type=submit]"

          [[flows.steps]]
          action = "wait"
          ms = 500
        """,
    )
    cfg = load_config(p)
    assert len(cfg.flows) == 1
    flow = cfg.flows[0]
    assert flow.name == "login"
    assert len(flow.steps) == 5

    assert isinstance(flow.steps[0], NavigateStep)
    assert flow.steps[0].url == "/login"

    assert isinstance(flow.steps[1], CaptureStep)
    assert flow.steps[1].name == "login-empty"
    assert flow.steps[1].selector == "form"

    assert isinstance(flow.steps[2], FillStep)
    assert flow.steps[2].value == "test@example.com"

    assert isinstance(flow.steps[3], ClickStep)
    assert isinstance(flow.steps[4], WaitStep)
    assert flow.steps[4].ms == 500


def test_multiple_flows(tmp_path):
    p = write_toml(
        tmp_path,
        """
        [screenwright]
        base_url = "https://example.com"

        [[flows]]
        name = "flow-a"

          [[flows.steps]]
          action = "navigate"
          url = "/"

        [[flows]]
        name = "flow-b"

          [[flows.steps]]
          action = "navigate"
          url = "/about"
        """,
    )
    cfg = load_config(p)
    assert cfg.flow_names() == ["flow-a", "flow-b"]
    assert cfg.get_flow("flow-a") is not None
    assert cfg.get_flow("missing") is None


def test_vision_disable(tmp_path):
    p = write_toml(
        tmp_path,
        """
        [screenwright]
        vision_describe = false
        """,
    )
    cfg = load_config(p)
    assert cfg.vision_describe is False


def test_capture_step_no_selector(tmp_path):
    p = write_toml(
        tmp_path,
        """
        [screenwright]

        [[flows]]
        name = "test"

          [[flows.steps]]
          action = "capture"
          name = "full-page"
        """,
    )
    cfg = load_config(p)
    step = cfg.flows[0].steps[0]
    assert isinstance(step, CaptureStep)
    assert step.selector is None


def test_vision_config_defaults():
    vc = VisionConfig()
    assert vc.provider == "anthropic"
    assert vc.structured_metadata is True
    assert "documentation" in vc.prompt
