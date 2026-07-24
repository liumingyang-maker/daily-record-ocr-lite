"""Installation and configuration doctor with stable machine-readable output."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class InstallationCheckError(RuntimeError):
    """A correctness-critical installation check failed."""


def run_doctor(
    *,
    root: Path = ROOT,
    data_dir: Path | None = None,
    full: bool = False,
) -> dict[str, Any]:
    from lite_app import __version__
    from lite_app.contracts import validate_record_result
    from lite_app.final_result import project_final_result
    from lite_app.grouping.exporter import export_grouped_excel
    from lite_app.grouping.service import build_business_entities
    from lite_app.settings import SettingsService

    checks: list[dict[str, Any]] = []
    setup_required = False

    def add(
        identifier: str,
        status: str,
        message: str,
        *,
        critical: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        checks.append(
            {
                "id": identifier,
                "status": status,
                "message": message,
                "critical": critical,
                "details": details or {},
            }
        )

    version_ok = _pyproject_version(root) == __version__ == "1.0.1"
    add(
        "version",
        "PASS" if version_ok else "FAIL",
        f"应用版本 {__version__}",
        critical=True,
        details={
            "app_version": __version__,
            "pyproject_version": _pyproject_version(root),
            "git_tag": _git_exact_tag(root),
        },
    )

    supported_python = (3, 11) <= sys.version_info[:2] <= (3, 12)
    add(
        "python",
        "PASS" if supported_python else "FAIL",
        f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        critical=True,
    )
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    add(
        "venv",
        "PASS" if in_venv else "WARN",
        "已在虚拟环境中运行" if in_venv else "当前不在虚拟环境中",
    )

    core_modules = [
        "fastapi",
        "uvicorn",
        "jinja2",
        "httpx",
        "yaml",
        "PIL",
        "openpyxl",
        "jsonschema",
        "rapidfuzz",
        "numpy",
    ]
    missing_core = [module for module in core_modules if importlib.util.find_spec(module) is None]
    add(
        "core_packages",
        "FAIL" if missing_core else "PASS",
        "核心依赖完整" if not missing_core else f"缺少: {', '.join(missing_core)}",
        critical=True,
        details={"missing": missing_core},
    )

    ocr_modules = ["paddle", "paddleocr", "cv2"]
    missing_ocr = [module for module in ocr_modules if importlib.util.find_spec(module) is None]
    if missing_ocr:
        setup_required = True
    add(
        "ocr_packages",
        "WARN" if missing_ocr else "PASS",
        "OCR 依赖待安装" if missing_ocr else "Paddle/PaddleOCR/OpenCV 已安装",
        details={"missing": missing_ocr},
    )

    service = SettingsService(data_dir or root / "data")
    try:
        effective = service.effective_settings()
        service.status()
    except Exception as exc:
        effective = {}
        add("settings", "FAIL", str(exc), critical=True)
    else:
        add("settings", "PASS", "settings-v1 可读取")

    ocr = effective.get("ocr", {})
    valid_ocr_provider = ocr.get("provider") in {"paddleocr_v6", "mock"}
    if ocr.get("provider") == "mock" and not effective.get("demo_mode"):
        valid_ocr_provider = False
    add(
        "ocr_config",
        "PASS" if valid_ocr_provider else "FAIL",
        f"provider={ocr.get('provider', '')}, tier={ocr.get('tier', '')}, "
        f"device={ocr.get('device', '')}",
        critical=not valid_ocr_provider,
    )
    if not missing_ocr and ocr.get("provider") == "paddleocr_v6":
        try:
            from lite_app.ocr.manager import OCRModelManager

            manager = OCRModelManager()
            manager.configure(ocr)
            manager.ensure_loaded()
            service.record_health("ocr", True)
            add("ocr_provider_load", "PASS", "PP-OCRv6 provider loaded")
        except Exception as exc:
            service.record_health("ocr", False)
            add("ocr_provider_load", "FAIL", str(exc), critical=True)

    vision = effective.get("vision", {})
    api_key_configured = bool(vision.get("api_key"))
    vision_configured = (
        vision.get("provider") == "openai_compatible"
        and bool(vision.get("base_url"))
        and bool(vision.get("model"))
        and api_key_configured
    )
    demo_mode = bool(effective.get("demo_mode"))
    if not vision_configured or demo_mode:
        setup_required = True
    add(
        "vision",
        "PASS" if vision_configured and not demo_mode else "WARN",
        ("真实视觉模型已配置" if vision_configured and not demo_mode else "真实视觉模型尚未就绪"),
        details={
            "provider": vision.get("provider", ""),
            "model": vision.get("model", ""),
            "base_url_configured": bool(vision.get("base_url")),
            "api_key_configured": api_key_configured,
            "demo_mode": demo_mode,
        },
    )

    doctor_data_dir = service.data_dir
    try:
        doctor_data_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=doctor_data_dir, delete=True) as handle:
            handle.write(b"doctor")
            handle.flush()
        add("data_directory", "PASS", f"可写: {doctor_data_dir}")
    except OSError as exc:
        add("data_directory", "FAIL", str(exc), critical=True)

    port = int(os.environ.get("APP_PORT", "8765"))
    available = _port_available(port)
    add(
        "port",
        "PASS" if available else "WARN",
        f"127.0.0.1:{port} " + ("可用" if available else "已被占用"),
    )

    mock_path = root / "config" / "mock_result.json"
    try:
        mock_result = json.loads(mock_path.read_text("utf-8"))
        record_report = validate_record_result(mock_result)
        if record_report.issues:
            raise RuntimeError(record_report.issues[0].message)
        add("record_schema", "PASS", "record-v1/Prompt/Mock 一致")
    except Exception as exc:
        mock_result = {}
        add("record_schema", "FAIL", str(exc), critical=True)

    try:
        final = project_final_result("doctor", mock_result, {"fields": []})
        final_report = validate_record_result(final)
        if final_report.issues:
            raise RuntimeError(final_report.issues[0].message)
        add("final_result_schema", "PASS", "正式 FinalResult 通过 record-v1")
    except Exception as exc:
        final = {}
        add("final_result_schema", "FAIL", str(exc), critical=True)

    try:
        entities = build_business_entities("doctor", final)
        with tempfile.TemporaryDirectory(dir=doctor_data_dir) as temp_dir:
            workbook_path = Path(temp_dir) / "doctor.xlsx"
            export_grouped_excel(entities, workbook_path)
            if not workbook_path.exists() or workbook_path.stat().st_size == 0:
                raise RuntimeError("Excel 文件为空")
        add("excel_export", "PASS", "FinalResult 基本 Excel 导出成功")
    except Exception as exc:
        add("excel_export", "FAIL", str(exc), critical=True)

    add(
        "demo_mode",
        "WARN" if demo_mode else "PASS",
        "演示模式已开启" if demo_mode else "演示模式关闭",
    )

    if full and not missing_ocr and ocr.get("provider") == "paddleocr_v6":
        try:
            result = asyncio.run(_full_ocr_check(service))
            service.record_health("ocr", True)
            add("ocr_inference", "PASS", "真实 OCR 推理成功", details=result)
        except Exception as exc:
            service.record_health("ocr", False)
            add("ocr_inference", "FAIL", str(exc), critical=True)
    if full and vision_configured and not demo_mode:
        try:
            result = asyncio.run(_full_vision_check(service))
            service.record_health("vision", True)
            add("vision_connection", "PASS", "视觉模型连接成功", details=result)
        except Exception as exc:
            service.record_health("vision", False)
            add("vision_connection", "FAIL", str(exc), critical=True)

    broken = any(check["status"] == "FAIL" and check["critical"] for check in checks)
    try:
        current_setup_state = service.status().get("state")
    except Exception:
        current_setup_state = "BROKEN"
    if broken:
        state, exit_code = "BROKEN", 2
    elif setup_required or current_setup_state != "READY_FOR_RECOGNITION":
        state, exit_code = "SETUP_REQUIRED", 1
    else:
        state, exit_code = "READY", 0
    return {
        "schema_version": "doctor-v1",
        "state": state,
        "exit_code": exit_code,
        "version": __version__,
        "checks": checks,
    }


async def _full_ocr_check(service) -> dict[str, Any]:
    from PIL import Image, ImageDraw, ImageFont

    from lite_app.ocr.manager import OCRModelManager

    service.data_dir.mkdir(parents=True, exist_ok=True)
    image_path = service.data_dir / "doctor-real-ocr.png"
    image = Image.new("RGB", (720, 180), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 46)
    except OSError:
        font = ImageFont.load_default()
    draw.text((35, 55), "PA66 0.15 kg", fill="black", font=font)
    image.save(image_path)
    manager = OCRModelManager()
    manager.configure(service.effective_settings()["ocr"])
    try:
        page = await manager.recognize_async(image_path)
    finally:
        image_path.unlink(missing_ok=True)
    if not page.tokens:
        raise RuntimeError("真实 OCR 推理返回 0 个 token")
    return {
        "provider": page.provider,
        "model": page.model,
        "token_count": len(page.tokens),
        "token_preview": [token.text for token in page.tokens[:8]],
        "elapsed_ms": page.elapsed_ms,
    }


async def _full_vision_check(service) -> dict[str, Any]:
    from lite_app.pipeline_v2 import build_vision_provider
    from lite_app.vision.probe import (
        PROBE_SCHEMA,
        PROBE_SYSTEM_PROMPT,
        PROBE_USER_PROMPT,
        create_probe_image,
        validate_probe_response,
    )

    service.data_dir.mkdir(parents=True, exist_ok=True)
    image_path = service.data_dir / "doctor-vision.png"
    create_probe_image(image_path)
    provider = build_vision_provider(service.effective_settings()["vision"])
    try:
        raw = await provider.analyze(
            [image_path],
            PROBE_SYSTEM_PROMPT,
            PROBE_USER_PROMPT,
            PROBE_SCHEMA,
        )
    finally:
        image_path.unlink(missing_ok=True)
    if not validate_probe_response(raw):
        raise RuntimeError("视觉模型未正确读取测试图片中的标记")
    return {"response_received": True, "vision_capability": True}


def _pyproject_version(root: Path) -> str:
    import tomllib

    try:
        with (root / "pyproject.toml").open("rb") as handle:
            return str(tomllib.load(handle)["project"]["version"])
    except Exception:
        return ""


def _git_exact_tag(root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "describe", "--tags", "--exact-match"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _port_available(port: int) -> bool:
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _safe_print(value: str) -> None:
    """Print without crashing on legacy Windows console encodings."""
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        value.encode(encoding)
    except (LookupError, UnicodeEncodeError):
        value = value.encode(encoding, errors="backslashreplace").decode(encoding)
    print(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检查 daily-record-ocr-lite 安装")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--full", action="store_true")
    parser.add_argument(
        "--gate",
        action="store_true",
        help="把 READY/SETUP_REQUIRED 都视为安装成功，仅 BROKEN 返回失败",
    )
    args = parser.parse_args(argv)
    try:
        report = run_doctor(full=args.full)
    except Exception as exc:
        report = {
            "schema_version": "doctor-v1",
            "state": "BROKEN",
            "exit_code": 2,
            "version": "",
            "checks": [
                {
                    "id": "unexpected_exception",
                    "status": "FAIL",
                    "message": str(exc),
                    "critical": True,
                    "details": {},
                }
            ],
        }
    if args.as_json:
        _safe_print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    else:
        _safe_print(f"daily-record-ocr-lite doctor: {report['state']}")
        for check in report["checks"]:
            _safe_print(f"[{check['status']}] {check['id']}: {check['message']}")
    if args.gate:
        return 2 if report["state"] == "BROKEN" else 0
    return int(report["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
