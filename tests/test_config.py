from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from screenwright.config import (
    CaptureStep,
    ClickStep,
    FillStep,
    Flow,
    NavigateStep,
    ScreenwrightConfig,
    Variant,
    VisionConfig,
    WaitStep,
    load_config,
)


def test_fill_step_secret_requires_env_ref():
    with pytest.raises(ValidationError):
        FillStep(action="fill", selector="#password", value="hunter2", secret=True)


def test_fill_step_secret_accepts_env_ref():
    step = FillStep(action="fill", selector="#password", value="${DB_PASSWORD}", secret=True)
    assert step.value == "${DB_PASSWORD}"


def test_fill_step_non_secret_accepts_literal_or_env_ref():
    assert FillStep(action="fill", selector="#email", value="demo@example.com").value == (
        "demo@example.com"
    )
    assert FillStep(action="fill", selector="#email", value="${EMAIL}").value == "${EMAIL}"


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


def test_load_rejects_duplicate_flow_names(tmp_path):
    # Every flow's output path is derived from its name — two flows
    # sharing a name would silently write to the same directory, one
    # overwriting the other (or racing under --concurrency > 1). A
    # copy-paste typo in TOML is the realistic way to trigger this, so
    # it's caught here rather than producing confusing output.
    p = write_toml(
        tmp_path,
        """
        [[flows]]
        name = "homepage"

          [[flows.steps]]
          action = "navigate"
          url = "/"

        [[flows]]
        name = "homepage"

          [[flows.steps]]
          action = "navigate"
          url = "/about"
        """,
    )
    with pytest.raises(ValidationError, match="Duplicate flow name"):
        load_config(p)


def test_screenwright_config_accepts_unique_flow_names_directly():
    cfg = ScreenwrightConfig(
        flows=[Flow(name="a", steps=[]), Flow(name="b", steps=[])],
    )
    assert cfg.flow_names() == ["a", "b"]


def test_screenwright_config_rejects_duplicate_flow_names_directly():
    with pytest.raises(ValidationError, match="Duplicate flow name"):
        ScreenwrightConfig(
            flows=[Flow(name="a", steps=[]), Flow(name="a", steps=[])],
        )


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


@pytest.mark.parametrize(
    "bad_name",
    [
        "../../etc/passwd",
        "..",
        ".",
        "foo/bar",
        "foo\\bar",
        "/etc/passwd",
        "a..b",  # contains ".." even though it's not the whole segment
        "",
    ],
)
def test_capture_step_rejects_path_traversal_names(bad_name):
    with pytest.raises(ValidationError):
        CaptureStep(action="capture", name=bad_name)


@pytest.mark.parametrize(
    "bad_name",
    ["../escape", ".."],
)
def test_flow_rejects_path_traversal_names(bad_name):
    with pytest.raises(ValidationError):
        Flow(name=bad_name)


def test_capture_step_accepts_safe_names():
    assert CaptureStep(action="capture", name="homepage-full_v2.1").name == "homepage-full_v2.1"


def test_capture_step_accessibility_snapshot_defaults_to_false():
    assert CaptureStep(action="capture", name="shot").accessibility_snapshot is False


def test_capture_step_accepts_accessibility_snapshot():
    step = CaptureStep(action="capture", name="shot", accessibility_snapshot=True)
    assert step.accessibility_snapshot is True


def test_capture_step_pdf_defaults_to_false():
    assert CaptureStep(action="capture", name="shot").pdf is False


def test_capture_step_accepts_pdf():
    assert CaptureStep(action="capture", name="shot", pdf=True).pdf is True


def test_capture_step_variants_defaults_to_empty_list():
    assert CaptureStep(action="capture", name="shot").variants == []


def test_capture_step_accepts_variants():
    step = CaptureStep(
        action="capture",
        name="shot",
        variants=[
            {"name": "mobile", "viewport_width": 390, "viewport_height": 844},
            {"name": "dark", "color_scheme": "dark"},
        ],
    )
    assert len(step.variants) == 2
    assert step.variants[0].name == "mobile"
    assert step.variants[0].viewport_width == 390
    assert step.variants[1].color_scheme == "dark"


def test_variant_rejects_path_traversal_name():
    with pytest.raises(ValidationError):
        Variant(name="../escape")


def test_capture_step_deterministic_defaults():
    step = CaptureStep(action="capture", name="shot")
    assert step.animations == "disabled"
    assert step.mask == []
    assert step.mask_color is None


def test_capture_step_accepts_animations_allow():
    step = CaptureStep(action="capture", name="shot", animations="allow")
    assert step.animations == "allow"


def test_capture_step_accepts_mask_selectors_and_color():
    step = CaptureStep(
        action="capture", name="shot", mask=["#clock", ".avatar"], mask_color="#000000"
    )
    assert step.mask == ["#clock", ".avatar"]
    assert step.mask_color == "#000000"


def test_flow_har_defaults_to_false():
    assert Flow(name="test").har is False


def test_flow_accepts_har():
    assert Flow(name="test", har=True).har is True
