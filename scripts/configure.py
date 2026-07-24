"""AI- and human-facing configuration CLI backed by SettingsService."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys
import time
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lite_app.config import PROJECT_ROOT
from lite_app.settings import SettingsError, SettingsService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="配置 daily-record-ocr-lite")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="显示非敏感配置状态")
    status.add_argument("--json", action="store_true", dest="as_json")

    vision = subparsers.add_parser("vision", help="配置视觉模型")
    vision.add_argument("--provider", default="openai_compatible")
    vision.add_argument("--base-url", required=True)
    vision.add_argument("--endpoint", default="/chat/completions")
    vision.add_argument("--model", required=True)

    key = subparsers.add_parser("set-key", help="安全写入视觉模型 API Key")
    key.add_argument(
        "--from-env",
        metavar="NAME",
        help="从指定环境变量读取；不把密钥放入命令行历史",
    )

    test_vision = subparsers.add_parser("test-vision", help="测试视觉模型连接")
    test_vision.add_argument("--json", action="store_true", dest="as_json")

    ocr = subparsers.add_parser("ocr", help="配置 PP-OCRv6")
    ocr.add_argument("--provider", default="paddleocr_v6")
    ocr.add_argument("--tier", choices=["tiny", "small", "medium"], default="medium")
    ocr.add_argument("--device", default="cpu")
    ocr.add_argument("--minimum-score", type=float, default=0.45)

    test_ocr = subparsers.add_parser("test-ocr", help="加载 OCR 并识别测试图片")
    test_ocr.add_argument("--image", type=Path)
    test_ocr.add_argument("--json", action="store_true", dest="as_json")
    return parser


def run(
    argv: list[str] | None = None,
    *,
    data_dir: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    service = SettingsService(data_dir or PROJECT_ROOT / "data")
    environment = environ if environ is not None else os.environ
    try:
        if args.command == "status":
            status = service.status()
            _print(status, args.as_json)
            return 0
        if args.command == "vision":
            service.configure_vision(
                {
                    "provider": args.provider,
                    "base_url": args.base_url,
                    "endpoint": args.endpoint,
                    "model": args.model,
                }
            )
            print("视觉模型非敏感配置已保存；API Key 状态未回显。")
            return 0
        if args.command == "set-key":
            if args.from_env:
                api_key = environment.get(args.from_env, "")
                if not api_key:
                    print(f"环境变量 {args.from_env} 为空。", file=sys.stderr)
                    return 2
            else:
                api_key = getpass.getpass("Vision API Key（输入不会显示）: ")
            service.set_api_key(api_key)
            print("API Key 已保存；不会在配置输出中回显。")
            return 0
        if args.command == "ocr":
            service.configure_ocr(
                {
                    "provider": args.provider,
                    "tier": args.tier,
                    "device": args.device,
                    "minimum_score": args.minimum_score,
                }
            )
            print(
                f"OCR 配置已保存：provider={args.provider}, "
                f"tier={args.tier}, device={args.device}"
            )
            return 0
        if args.command == "test-vision":
            result = asyncio.run(_test_vision(service))
            _print(result, args.as_json)
            return 0
        if args.command == "test-ocr":
            result = asyncio.run(_test_ocr(service, args.image))
            _print(result, args.as_json)
            return 0
    except (SettingsError, RuntimeError, OSError) as exc:
        print(f"配置命令失败: {exc}", file=sys.stderr)
        return 2
    return 2


async def _test_vision(service: SettingsService) -> dict:
    from lite_app.pipeline_v2 import build_vision_provider
    from lite_app.vision.probe import (
        PROBE_SCHEMA,
        PROBE_SYSTEM_PROMPT,
        PROBE_USER_PROMPT,
        create_probe_image,
        validate_probe_response,
    )

    effective = service.effective_settings()
    if effective["demo_mode"]:
        return {
            "status": "DEMO_MODE",
            "message": "演示模式未发起真实视觉连接。",
        }
    vision = effective["vision"]
    provider = build_vision_provider(vision)
    service.data_dir.mkdir(parents=True, exist_ok=True)
    image_path = service.data_dir / "cli-vision-test.png"
    create_probe_image(image_path)
    started = time.monotonic()
    try:
        try:
            raw = await provider.analyze(
                [image_path],
                PROBE_SYSTEM_PROMPT,
                PROBE_USER_PROMPT,
                PROBE_SCHEMA,
            )
        except Exception:
            service.record_health("vision", False)
            raise
    finally:
        image_path.unlink(missing_ok=True)
    if not validate_probe_response(raw):
        service.record_health("vision", False)
        raise RuntimeError("视觉模型未正确读取测试图片中的标记")
    service.record_health("vision", True)
    return {
        "status": "OK",
        "provider": vision.get("provider", ""),
        "model": vision.get("model", ""),
        "latency_ms": int((time.monotonic() - started) * 1000),
        "vision_capability": True,
        "json_response_capability": True,
    }


async def _test_ocr(service: SettingsService, image_path: Path | None) -> dict:
    from PIL import Image, ImageDraw, ImageFont

    from lite_app.ocr.manager import OCRModelManager

    generated = False
    if image_path is None:
        service.data_dir.mkdir(parents=True, exist_ok=True)
        image_path = service.data_dir / "cli-ocr-test.png"
        image = Image.new("RGB", (720, 260), "white")
        draw = ImageDraw.Draw(image)
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", 42)
        except OSError:
            font = ImageFont.load_default()
        draw.text((40, 35), "PA66 60kg", fill="black", font=font)
        draw.text((40, 105), "GF30 30kg", fill="black", font=font)
        draw.text((40, 175), "Process 50Hz", fill="black", font=font)
        image.save(image_path)
        generated = True
    if not image_path.exists():
        raise RuntimeError(f"测试图片不存在: {image_path}")
    manager = OCRModelManager()
    manager.configure(service.effective_settings()["ocr"])
    try:
        try:
            page = await manager.recognize_async(image_path)
        except Exception:
            service.record_health("ocr", False)
            raise
    finally:
        if generated:
            image_path.unlink(missing_ok=True)
    if not page.tokens:
        service.record_health("ocr", False)
        raise RuntimeError("真实 OCR 测试未返回 token")
    service.record_health("ocr", True)
    return {
        "status": "OK",
        "provider": page.provider,
        "model": page.model,
        "token_count": len(page.tokens),
        "token_preview": [token.text for token in page.tokens[:8]],
        "average_confidence": page.average_confidence,
        "elapsed_ms": page.elapsed_ms,
    }


def _print(payload: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    for key, value in payload.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    raise SystemExit(run())
