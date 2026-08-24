from __future__ import annotations

import types

import pytest

from screenwright.config import VisionConfig
from screenwright.vision import (
    _build_prompt,
    _describe_anthropic,
    _describe_openai,
    _first_text_block,
    _is_transient,
    _parse_response,
    _with_retry,
)


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


def test_parse_response_does_not_swallow_unrelated_errors(monkeypatch):
    # The fallback only covers "the model didn't return the JSON shape we
    # asked for" (JSONDecodeError / pydantic ValidationError). A genuine bug
    # elsewhere in this code path — simulated here as json.loads raising
    # something else entirely — must propagate, not get silently absorbed
    # into "treat it as a plain-text description".
    def broken_loads(_text):
        raise TypeError("simulated unrelated bug")

    monkeypatch.setattr("screenwright.vision.json.loads", broken_loads)
    with pytest.raises(TypeError):
        _parse_response('{"description": "x"}', structured=True)


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


def test_first_text_block_skips_non_text_blocks():
    blocks = [
        types.SimpleNamespace(type="thinking", text="internal reasoning"),
        types.SimpleNamespace(type="text", text="the actual description"),
    ]
    assert _first_text_block(blocks) == "the actual description"


def test_first_text_block_returns_empty_string_when_none_found():
    blocks = [types.SimpleNamespace(type="tool_use", text="irrelevant")]
    assert _first_text_block(blocks) == ""


def test_first_text_block_handles_empty_list():
    assert _first_text_block([]) == ""


class _FakeAnthropicMessages:
    def __init__(self, message):
        self._message = message

    def create(self, **kwargs):
        return self._message


class _FakeAnthropicClient:
    def __init__(self, message):
        self.messages = _FakeAnthropicMessages(message)


def test_describe_anthropic_uses_first_text_block(monkeypatch, tmp_path):
    import anthropic

    image = tmp_path / "shot.png"
    image.write_bytes(b"fake-png")

    message = types.SimpleNamespace(
        content=[types.SimpleNamespace(type="text", text="A login form")],
        stop_reason="end_turn",
    )
    monkeypatch.setattr(anthropic, "Anthropic", lambda: _FakeAnthropicClient(message))

    result = _describe_anthropic(image, VisionConfig(structured_metadata=False))
    assert result.description == "A login form"


def test_describe_anthropic_warns_on_truncation(monkeypatch, tmp_path):
    import anthropic

    image = tmp_path / "shot.png"
    image.write_bytes(b"fake-png")

    message = types.SimpleNamespace(
        content=[types.SimpleNamespace(type="text", text="cut off mid-")],
        stop_reason="max_tokens",
    )
    monkeypatch.setattr(anthropic, "Anthropic", lambda: _FakeAnthropicClient(message))

    with pytest.warns(UserWarning, match="truncated"):
        _describe_anthropic(image, VisionConfig(structured_metadata=False))


class _FakeOpenAIChoice:
    def __init__(self, content, finish_reason="stop"):
        self.message = types.SimpleNamespace(content=content)
        self.finish_reason = finish_reason


class _FakeOpenAICompletions:
    def __init__(self, choice):
        self._choice = choice

    def create(self, **kwargs):
        return types.SimpleNamespace(choices=[self._choice])


class _FakeOpenAIClient:
    def __init__(self, choice):
        self.chat = types.SimpleNamespace(completions=_FakeOpenAICompletions(choice))


def test_describe_openai_handles_none_content_without_crashing(monkeypatch, tmp_path):
    import openai

    image = tmp_path / "shot.png"
    image.write_bytes(b"fake-png")

    choice = _FakeOpenAIChoice(content=None)
    monkeypatch.setattr(openai, "OpenAI", lambda: _FakeOpenAIClient(choice))

    result = _describe_openai(image, VisionConfig(structured_metadata=False))
    assert result.description == ""


def test_describe_openai_warns_on_truncation(monkeypatch, tmp_path):
    import openai

    image = tmp_path / "shot.png"
    image.write_bytes(b"fake-png")

    choice = _FakeOpenAIChoice(content="cut off mid-", finish_reason="length")
    monkeypatch.setattr(openai, "OpenAI", lambda: _FakeOpenAIClient(choice))

    with pytest.warns(UserWarning, match="truncated"):
        _describe_openai(image, VisionConfig(structured_metadata=False))


def test_describe_openai_returns_normal_description(monkeypatch, tmp_path):
    import openai

    image = tmp_path / "shot.png"
    image.write_bytes(b"fake-png")

    choice = _FakeOpenAIChoice(content="A homepage hero section")
    monkeypatch.setattr(openai, "OpenAI", lambda: _FakeOpenAIClient(choice))

    result = _describe_openai(image, VisionConfig(structured_metadata=False))
    assert result.description == "A homepage hero section"
