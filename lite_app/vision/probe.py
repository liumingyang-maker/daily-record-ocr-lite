"""A licensed local visual probe that text-only models cannot answer correctly."""

from __future__ import annotations

import json
from pathlib import Path

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


def validate_probe_response(raw: str) -> bool:
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return False
    return isinstance(parsed, dict) and parsed.get("marker") == PROBE_MARKER
