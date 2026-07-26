from __future__ import annotations

import base64
import json
from pathlib import Path

from pydantic import BaseModel, Field

from screenwright.config import VisionConfig


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
    except (json.JSONDecodeError, Exception):
        # Graceful fallback: treat entire response as the description
        return ScreenshotMetadata(description=text.strip())


def _encode_image(image_path: Path) -> str:
    with open(image_path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


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
    return _parse_response(message.content[0].text, cfg.structured_metadata)


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


def describe(image_path: Path, cfg: VisionConfig) -> ScreenshotMetadata:
    """Describe a screenshot using the configured vision provider."""
    if cfg.provider == "anthropic":
        return _describe_anthropic(image_path, cfg)
    elif cfg.provider == "ollama":
        return _describe_ollama(image_path, cfg)
    else:
        raise ValueError(f"Unknown vision provider: {cfg.provider!r}. Use 'anthropic' or 'ollama'.")
