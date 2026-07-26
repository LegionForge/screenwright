from __future__ import annotations

from screenwright.config import VisionConfig
from screenwright.vision import _build_prompt, _parse_response


def test_build_prompt_appends_structured_suffix_when_enabled():
    cfg = VisionConfig(prompt="Base prompt.", structured_metadata=True)
    prompt = _build_prompt(cfg)
    assert prompt.startswith("Base prompt.")
    assert "Return ONLY a JSON object" in prompt


def test_build_prompt_omits_structured_suffix_when_disabled():
    cfg = VisionConfig(prompt="Base prompt.", structured_metadata=False)
    assert _build_prompt(cfg) == "Base prompt."


def test_parse_response_unstructured_returns_raw_text():
    result = _parse_response("  A plain description.  ", structured=False)
    assert result.description == "A plain description."
    assert result.components == []


def test_parse_response_structured_parses_valid_json():
    text = (
        '{"description": "Login form", "components": ["form", "button"], '
        '"state": "empty", "title": "Sign In", "errors_visible": false, '
        '"accessibility_notes": ""}'
    )
    result = _parse_response(text, structured=True)
    assert result.description == "Login form"
    assert result.components == ["form", "button"]
    assert result.state == "empty"
    assert result.title == "Sign In"


def test_parse_response_structured_strips_markdown_fences():
    text = '```json\n{"description": "Fenced JSON"}\n```'
    result = _parse_response(text, structured=True)
    assert result.description == "Fenced JSON"


def test_parse_response_structured_falls_back_on_invalid_json():
    text = "Not JSON at all"
    result = _parse_response(text, structured=True)
    assert result.description == "Not JSON at all"
    assert result.components == []


def test_parse_response_structured_falls_back_on_empty_text():
    # Some small local vision models (e.g. moondream) return an empty
    # completion when asked to follow the structured JSON prompt. The
    # fallback must not raise — it should produce an (empty) description
    # rather than crash the pipeline.
    result = _parse_response("", structured=True)
    assert result.description == ""


def test_parse_response_structured_falls_back_when_required_field_missing():
    # Valid JSON but missing the required "description" key should not
    # raise a validation error — it should fall back to raw-text mode.
    text = '{"components": ["form"]}'
    result = _parse_response(text, structured=True)
    assert result.description == text
