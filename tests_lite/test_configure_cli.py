"""The AI-facing configuration CLI shares SettingsService with Web."""

from __future__ import annotations

import json
import os

from scripts.configure import run


def test_cli_configures_vision_without_echoing_secret(tmp_path, capsys):
    assert (
        run(
            [
                "vision",
                "--provider",
                "openai_compatible",
                "--base-url",
                "https://example.invalid/v1",
                "--model",
                "vision-model",
            ],
            data_dir=tmp_path,
        )
        == 0
    )
    assert (
        run(
            ["set-key", "--from-env", "TEST_VISION_KEY"],
            data_dir=tmp_path,
            environ={"TEST_VISION_KEY": "secret-from-env"},
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "secret-from-env" not in output
    assert "API Key 已保存" in output

    settings = json.loads((tmp_path / "settings.json").read_text("utf-8"))
    assert settings["vision"]["model"] == "vision-model"
    assert "api_key" not in settings["vision"]
    assert "secret-from-env" in (tmp_path / "secrets.env").read_text("utf-8")


def test_cli_status_is_json_and_secret_safe(tmp_path, capsys):
    from lite_app.settings import SettingsService

    service = SettingsService(tmp_path)
    service.set_api_key("never-print-this")
    assert run(["status", "--json"], data_dir=tmp_path) == 0
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["api_key_configured"] is True
    assert "never-print-this" not in output


def test_cli_configures_official_ocr_tier(tmp_path):
    assert (
        run(
            [
                "ocr",
                "--provider",
                "paddleocr_v6",
                "--tier",
                "small",
                "--device",
                "cpu",
            ],
            data_dir=tmp_path,
        )
        == 0
    )
    settings = json.loads((tmp_path / "settings.json").read_text("utf-8"))
    assert settings["ocr"] == {
        "provider": "paddleocr_v6",
        "tier": "small",
        "device": "cpu",
        "minimum_score": 0.45,
    }


def test_health_is_bound_to_current_configuration_and_key(tmp_path, monkeypatch):
    from lite_app.settings import SettingsService

    for name in (
        "VISION_API_KEY",
        "VISION_PROVIDER",
        "VISION_BASE_URL",
        "VISION_ENDPOINT",
        "VISION_MODEL",
        "OCR_PROVIDER",
        "OCR_TIER",
        "OCR_DEVICE",
        "OCR_MIN_SCORE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DEMO_MODE", "false")
    service = SettingsService(tmp_path)
    service.configure_vision(
        {
            "provider": "openai_compatible",
            "base_url": "https://example.invalid/v1",
            "model": "vision-model",
        }
    )
    service.set_api_key("first-key")
    assert service.status()["state"] == "SETUP_REQUIRED"

    service.record_health("ocr", True)
    service.record_health("vision", True)
    assert service.status()["state"] == "READY_FOR_RECOGNITION"

    service.set_api_key("rotated-key")
    assert service.status()["state"] == "SETUP_REQUIRED"
    assert service.effective_settings()["vision"]["api_key"] == "rotated-key"
    assert os.environ.get("VISION_API_KEY") != "first-key"
    assert "first-key" not in json.dumps(service.public_settings())


def test_visual_probe_must_read_marker_before_health_is_ready(
    tmp_path, monkeypatch, capsys
):
    from lite_app import pipeline_v2
    from lite_app.settings import SettingsService

    for name in (
        "VISION_PROVIDER",
        "VISION_BASE_URL",
        "VISION_ENDPOINT",
        "VISION_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DEMO_MODE", "false")
    service = SettingsService(tmp_path)
    service.configure_vision(
        {
            "provider": "openai_compatible",
            "base_url": "https://example.invalid/v1",
            "model": "vision-model",
        }
    )
    service.set_api_key("test-key")

    class FakeProvider:
        async def analyze(self, *_args, **_kwargs):
            return '{"marker": "VISION-7319"}'

    monkeypatch.setattr(
        pipeline_v2, "build_vision_provider", lambda _config: FakeProvider()
    )
    assert run(["test-vision", "--json"], data_dir=tmp_path) == 0
    assert json.loads(capsys.readouterr().out)["vision_capability"] is True
    assert service.status()["vision_healthy"] is True
