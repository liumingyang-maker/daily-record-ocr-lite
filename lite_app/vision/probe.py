"""A licensed local visual probe that text-only models cannot answer correctly."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

PROBE_MARKER = "VISION-7319"
PROBE_SYSTEM_PROMPT = "你是视觉能力检测器。必须读取图片，不要猜测。只返回 JSON。"
PROBE_USER_PROMPT = (
    '读取图片中央的黑色标记，返回 {"marker": "你看到的完整标记"}。'
)
PROBE_SCHEMA = {
    "type": "object",
    "properties": {"marker": {"type": "string", "pattern": "^VISION-[0-9]{4}$"}},
    "required": ["marker"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class ProbeResponse:
    parsed: dict[str, Any] | None
    vision_capability: bool
    json_response_capability: bool
    strict_json_capability: bool


def create_probe_image(path: Path) -> None:
    image = Image.new("RGB", (720, 220), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 64)
    except OSError:
        font = ImageFont.load_default()
    draw.rectangle((18, 18, 701, 201), outline="black", width=5)
    draw.text((105, 68), PROBE_MARKER, fill="black", font=font)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _json_object(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _remove_json_fence(raw: str) -> str:
    lines = raw.strip().splitlines()
    if lines and lines[0].strip().lower() in {"```", "```json"}:
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_first_json_object(raw: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for index, character in enumerate(raw):
        if character != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(raw[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def evaluate_probe_response(raw: str) -> ProbeResponse:
    if not isinstance(raw, str):
        return ProbeResponse(None, False, False, False)

    strict = False
    parsed = None
    try:
        parsed = _json_object(json.loads(raw))
        strict = True
    except json.JSONDecodeError:
        pass

    fenced = _remove_json_fence(raw)
    if parsed is None and fenced != raw:
        try:
            parsed = _json_object(json.loads(fenced))
        except json.JSONDecodeError:
            pass
    if parsed is None:
        parsed = _extract_first_json_object(fenced)

    json_capability = parsed is not None
    vision_capability = json_capability and parsed.get("marker") == PROBE_MARKER
    return ProbeResponse(parsed, vision_capability, json_capability, strict)


def validate_probe_response(raw: str) -> bool:
    return evaluate_probe_response(raw).vision_capability


def safe_response_preview(raw: str, *secrets: str) -> str:
    preview = str(raw)
    for secret in secrets:
        if secret:
            preview = preview.replace(secret, "[REDACTED]")
    preview = "".join(
        "[REDACTED AUTHORIZATION]\n"
        if "authorization:" in line.lower()
        else line
        for line in preview.splitlines(keepends=True)
    )
    return preview[:500]
