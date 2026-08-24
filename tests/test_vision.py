from __future__ import annotations

import pytest

from screenwright.config import VisionConfig
from screenwright.vision import _build_prompt, _is_transient, _parse_response, _with_retry


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


class _FakeRateLimitError(Exception):
    def __init__(self):
        self.status_code = 429


class _FakeAuthError(Exception):
    def __init__(self):
        self.status_code = 401


def test_is_transient_detects_status_code_on_exception():
    assert _is_transient(_FakeRateLimitError()) is True


def test_is_transient_rejects_non_retryable_status_code():
    assert _is_transient(_FakeAuthError()) is False


def test_is_transient_detects_timeout_and_connection_errors():
    assert _is_transient(TimeoutError()) is True
    assert _is_transient(ConnectionError()) is True
    assert _is_transient(ValueError("not transient")) is False


def test_with_retry_succeeds_after_transient_failures(monkeypatch):
    monkeypatch.setattr("screenwright.vision.time.sleep", lambda _seconds: None)
    calls = {"count": 0}

    def flaky():
        calls["count"] += 1
        if calls["count"] < 3:
            raise _FakeRateLimitError()
        return "ok"

    assert _with_retry(flaky) == "ok"
    assert calls["count"] == 3


def test_with_retry_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr("screenwright.vision.time.sleep", lambda _seconds: None)
    calls = {"count": 0}

    def always_flaky():
        calls["count"] += 1
        raise _FakeRateLimitError()

    with pytest.raises(_FakeRateLimitError):
        _with_retry(always_flaky)
    assert calls["count"] == 3  # 1 initial attempt + 2 retries


def test_with_retry_does_not_retry_non_transient_errors():
    calls = {"count": 0}

    def permanently_broken():
        calls["count"] += 1
        raise _FakeAuthError()

    with pytest.raises(_FakeAuthError):
        _with_retry(permanently_broken)
    assert calls["count"] == 1  # no retry attempted
