"""Installation doctor is machine-readable and fail-closed."""

from __future__ import annotations

import json

from scripts.doctor import main, run_doctor


def test_doctor_core_checks_are_healthy_without_real_providers(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("OCR_PROVIDER", "paddleocr_v6")
    monkeypatch.setenv("VISION_PROVIDER", "")
    monkeypatch.setenv("VISION_API_KEY", "")
    report = run_doctor(data_dir=tmp_path)
    assert report["state"] in {"SETUP_REQUIRED", "READY"}
    assert report["state"] != "BROKEN"
    checks = {check["id"]: check for check in report["checks"]}
    assert checks["record_schema"]["status"] == "PASS"
    assert checks["final_result_schema"]["status"] == "PASS"
    assert checks["excel_export"]["status"] == "PASS"


def test_doctor_json_never_contains_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("VISION_API_KEY", "doctor-must-not-print-this")
    report = run_doctor(data_dir=tmp_path)
    serialized = json.dumps(report)
    assert "doctor-must-not-print-this" not in serialized
    vision = next(check for check in report["checks"] if check["id"] == "vision")
    assert "api_key_configured" in vision["details"]


def test_doctor_provider_load_failure_is_broken(tmp_path, monkeypatch):
    import importlib.util

    from lite_app.ocr.manager import OCRModelManager

    original_find_spec = importlib.util.find_spec
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("OCR_PROVIDER", "paddleocr_v6")

    def fake_find_spec(name):
        if name in {"paddle", "paddleocr", "cv2"}:
            return object()
        return original_find_spec(name)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
    monkeypatch.setattr(
        OCRModelManager,
        "ensure_loaded",
        lambda _self: (_ for _ in ()).throw(RuntimeError("load failed")),
    )
    report = run_doctor(data_dir=tmp_path)
    assert report["state"] == "BROKEN"
    check = next(
        item for item in report["checks"] if item["id"] == "ocr_provider_load"
    )
    assert check["status"] == "FAIL"
    assert check["critical"] is True


def test_doctor_gate_never_fails_open_on_unexpected_exception(
    monkeypatch, capsys
):
    monkeypatch.setattr(
        "scripts.doctor.run_doctor",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("unexpected")),
    )
    assert main(["--json", "--gate"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["schema_version"] == "doctor-v1"
    assert report["state"] == "BROKEN"
