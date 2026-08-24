from __future__ import annotations

import base64
import json
import time
import warnings
from pathlib import Path
from typing import Callable, TypeVar

from pydantic import BaseModel, Field, ValidationError

from screenwright.config import VisionConfig

_T = TypeVar("_T")
_TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 2
_BACKOFF_BASE_SECONDS = 1.0


def _is_transient(exc: Exception) -> bool:
    """Best-effort check for retryable failures (rate limits, transient 5xx, timeouts).

    Deliberately conservative: retrying a non-transient failure (bad API key,
    malformed request) just burns time and cost for the same eventual error,
    so this only retries when there's a real signal the failure might clear.
    """
    status = getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None
    )
    if status in _TRANSIENT_STATUS_CODES:
        return True
    return isinstance(exc, (TimeoutError, ConnectionError))


def _with_retry(fn: Callable[[], _T]) -> _T:
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return fn()
        except Exception as exc:
            if attempt == _MAX_RETRIES or not _is_transient(exc):
                raise
            time.sleep(_BACKOFF_BASE_SECONDS * (2**attempt))
    raise AssertionError("unreachable")  # pragma: no cover


class ScreenshotMetadata(BaseModel):
    description: str
    components: list[str] = Field(default_factory=list)
    state: str = ""
    title: str = ""
    errors_visible: bool = False
    accessibility_notes: str = ""


_STRUCTURED_SUFFIX = (
    "\n\nReturn ONLY a JSON object with this exact structure and no other text:\n"
    "{\n"
    '  "description": "concise description of what the user sees",\n'
    '  "components": ["list", "of", "ui", "component", "types"],\n'
    '  "state": "e.g. empty, filled, error, loading, success",\n'
    '  "title": "page or modal title visible in the screenshot, or empty string",\n'
    '  "errors_visible": false,\n'
    '  "accessibility_notes": "notable accessibility issues, or empty string"\n'
    "}"
)


def _build_prompt(cfg: VisionConfig) -> str:
    base = cfg.prompt
    if cfg.structured_metadata:
        return base + _STRUCTURED_SUFFIX
    return base


def _parse_response(text: str, structured: bool) -> ScreenshotMetadata:
    if not structured:
        return ScreenshotMetadata(description=text.strip())

    # Strip markdown code fences if the model wrapped the JSON
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        data = json.loads(cleaned)
        return ScreenshotMetadata.model_validate(data)
    except (json.JSONDecodeError, ValidationError):
        # Graceful fallback: treat entire response as the description. Only
        # for "the model didn't return the JSON shape we asked for" — a bare
        # `except Exception` here would also swallow real bugs (e.g. a
        # TypeError from a caller passing something that isn't a string).
        return ScreenshotMetadata(description=text.strip())


def _encode_image(image_path: Path) -> str:
    with open(image_path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def _first_text_block(content_blocks) -> str:
    """Find the first text block in an Anthropic message's content list.

    ``message.content[0]`` isn't guaranteed to be a text block — depending
    on model/request config it could be a thinking block, a tool_use block,
    or the list could be empty. Scan for the first block with type "text"
    instead of assuming position 0, and return "" (handled gracefully by
    _parse_response) rather than raising if none is found.
    """
    for block in content_blocks:
        if getattr(block, "type", None) == "text":
            return block.text
    return ""


def _warn_if_truncated(provider: str, truncated: bool) -> None:
    if truncated:
        warnings.warn(
            f"{provider} vision response was truncated (max_tokens=512) — the "
            "description may be incomplete or fail structured-JSON parsing.",
            stacklevel=3,
        )


def _describe_anthropic(image_path: Path, cfg: VisionConfig) -> ScreenshotMetadata:
    import anthropic

    client = anthropic.Anthropic()
    prompt = _build_prompt(cfg)
    image_data = _encode_image(image_path)

    message = client.messages.create(
        model=cfg.model,
        max_tokens=512,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_data,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )
    _warn_if_truncated("Anthropic", message.stop_reason == "max_tokens")
    return _parse_response(_first_text_block(message.content), cfg.structured_metadata)


def _describe_ollama(image_path: Path, cfg: VisionConfig) -> ScreenshotMetadata:
    import ollama

    prompt = _build_prompt(cfg)
    with open(image_path, "rb") as f:
        image_bytes = f.read()

    response = ollama.chat(
        model=cfg.model,
        messages=[
            {
                "role": "user",
                "content": prompt,
                "images": [image_bytes],
            }
        ],
    )
    return _parse_response(response["message"]["content"], cfg.structured_metadata)


def _describe_openai(image_path: Path, cfg: VisionConfig) -> ScreenshotMetadata:
    import openai

    client = openai.OpenAI()
    prompt = _build_prompt(cfg)
    image_data = _encode_image(image_path)

    response = client.chat.completions.create(
        model=cfg.model,
        max_tokens=512,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_data}"},
                    },
                ],
            }
        ],
    )
    choice = response.choices[0]
    _warn_if_truncated("OpenAI", choice.finish_reason == "length")
    # content is None on a refusal or when the model emits tool_calls instead
    # of a text message — pass "" rather than crashing on .strip() downstream.
    return _parse_response(choice.message.content or "", cfg.structured_metadata)


def describe(image_path: Path, cfg: VisionConfig) -> ScreenshotMetadata:
    """Describe a screenshot using the configured vision provider.

    Transient failures (rate limits, 5xx, timeouts) are retried with
    exponential backoff — see _with_retry/_is_transient — but this still
    raises on the final attempt or on a non-transient error. Callers that
    describe multiple screenshots in a loop (cli.py's `run` command) should
    catch per-call, not assume this never raises.
    """
    if cfg.provider == "anthropic":
        return _with_retry(lambda: _describe_anthropic(image_path, cfg))
    elif cfg.provider == "ollama":
        return _with_retry(lambda: _describe_ollama(image_path, cfg))
    elif cfg.provider == "openai":
        return _with_retry(lambda: _describe_openai(image_path, cfg))
    else:
        raise ValueError(
            f"Unknown vision provider: {cfg.provider!r}. Use 'anthropic', 'ollama', or 'openai'."
        )
