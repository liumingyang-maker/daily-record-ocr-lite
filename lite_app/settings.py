"""Shared Web/CLI settings service with secret-safe public projections."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .contracts import load_schema_file
from .status import SetupState
from .storage import read_json_optional, write_json_atomic, write_text_atomic


class SettingsError(RuntimeError):
    """Settings are invalid or cannot be persisted."""


DEFAULT_SETTINGS: dict[str, Any] = {
    "schema_version": "settings-v1",
    "demo_mode": False,
    "ocr": {
        "provider": "paddleocr_v6",
        "tier": "medium",
        "device": "cpu",
        "minimum_score": 0.45,
    },
    "vision": {
        "provider": "",
        "base_url": "",
        "endpoint": "/chat/completions",
        "model": "",
    },
}


class SettingsService:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.settings_path = self.data_dir / "settings.json"
        self.secrets_path = self.data_dir / "secrets.env"
        self.health_path = self.data_dir / "setup_health.json"

    def load(self) -> dict[str, Any]:
        saved = read_json_optional(self.settings_path)
        settings = copy.deepcopy(DEFAULT_SETTINGS)
        if isinstance(saved, dict):
            settings.update({key: value for key, value in saved.items() if key in settings})
            if isinstance(saved.get("ocr"), dict):
                settings["ocr"].update(saved["ocr"])
            if isinstance(saved.get("vision"), dict):
                settings["vision"].update(saved["vision"])
        self._validate(settings)
        return settings

    def save(self, settings: dict[str, Any]) -> None:
        self._validate(settings)
        write_json_atomic(self.settings_path, settings)
        self._invalidate_health()
        from .config import clear_config_cache

        clear_config_cache()

    def status(self) -> dict[str, Any]:
        settings = self.effective_settings()
        demo = bool(settings["demo_mode"])
        vision = settings["vision"]
        key_configured = bool(self._load_secret() or os.environ.get("VISION_API_KEY"))
        vision_configured = (
            vision["provider"] == "openai_compatible"
            and bool(vision["base_url"])
            and bool(vision["model"])
            and key_configured
        )
        health = self._load_health(settings)
        ocr_healthy = bool(health.get("ocr"))
        vision_healthy = bool(health.get("vision"))
        if demo:
            state = SetupState.DEMO_MODE
        elif vision_configured and ocr_healthy and vision_healthy:
            state = SetupState.READY_FOR_RECOGNITION
        else:
            state = SetupState.SETUP_REQUIRED
        return {
            "state": state,
            "demo_mode": demo,
            "vision_configured": vision_configured,
            "ocr_healthy": ocr_healthy,
            "vision_healthy": vision_healthy,
            "api_key_configured": key_configured,
            "ocr": copy.deepcopy(settings["ocr"]),
        }

    def public_settings(self) -> dict[str, Any]:
        settings = self._with_environment(self.load())
        public = copy.deepcopy(settings)
        public["vision"]["api_key_configured"] = bool(
            self._load_secret() or os.environ.get("VISION_API_KEY")
        )
        return public

    def effective_settings(self) -> dict[str, Any]:
        settings = self._with_environment(self.load())
        effective = copy.deepcopy(settings)
        effective["vision"]["api_key"] = (
            os.environ.get("VISION_API_KEY", "") or self._load_secret()
        )
        return effective

    @staticmethod
    def _with_environment(settings: dict[str, Any]) -> dict[str, Any]:
        effective = copy.deepcopy(settings)
        vision_map = {
            "provider": "VISION_PROVIDER",
            "base_url": "VISION_BASE_URL",
            "endpoint": "VISION_ENDPOINT",
            "model": "VISION_MODEL",
        }
        ocr_map = {
            "provider": "OCR_PROVIDER",
            "tier": "OCR_TIER",
            "device": "OCR_DEVICE",
            "minimum_score": "OCR_MIN_SCORE",
        }
        for key, environment_name in vision_map.items():
            value = os.environ.get(environment_name, "").strip()
            if value:
                effective["vision"][key] = value
        for key, environment_name in ocr_map.items():
            value = os.environ.get(environment_name, "").strip()
            if value:
                effective["ocr"][key] = (
                    float(value) if key == "minimum_score" else value
                )
        if os.environ.get("DEMO_MODE", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            effective["demo_mode"] = True
        return effective

    def configure_vision(self, payload: dict[str, Any]) -> dict[str, Any]:
        settings = self.load()
        allowed = {"provider", "base_url", "endpoint", "model"}
        settings["vision"].update(
            {key: str(payload[key]).strip() for key in allowed if key in payload}
        )
        api_key = payload.get("api_key")
        if api_key is not None:
            self.set_api_key(str(api_key))
        settings["demo_mode"] = False
        self.save(settings)
        return self.public_settings()

    def configure_ocr(self, payload: dict[str, Any]) -> dict[str, Any]:
        settings = self.load()
        allowed = {"provider", "tier", "device", "minimum_score"}
        settings["ocr"].update(
            {key: payload[key] for key in allowed if key in payload}
        )
        self.save(settings)
        return self.public_settings()

    def enable_demo(self) -> dict[str, Any]:
        settings = self.load()
        settings["demo_mode"] = True
        settings["vision"]["provider"] = "mock"
        settings["ocr"]["provider"] = "mock"
        self.save(settings)
        return self.status()

    def disable_demo(self) -> dict[str, Any]:
        settings = self.load()
        settings["demo_mode"] = False
        if settings["vision"]["provider"] == "mock":
            settings["vision"]["provider"] = ""
        if settings["ocr"]["provider"] == "mock":
            settings["ocr"]["provider"] = "paddleocr_v6"
        self.save(settings)
        return self.status()

    def set_api_key(self, api_key: str) -> None:
        clean = api_key.strip().replace("\r", "").replace("\n", "")
        if not clean:
            if self.secrets_path.exists():
                self.secrets_path.unlink()
            self._invalidate_health()
            from .config import clear_config_cache

            clear_config_cache()
            return
        write_text_atomic(self.secrets_path, f"VISION_API_KEY={clean}\n")
        if os.name != "nt":
            self.secrets_path.chmod(0o600)
        self._invalidate_health()
        from .config import clear_config_cache

        clear_config_cache()

    def record_health(self, component: str, healthy: bool) -> None:
        if component not in {"ocr", "vision"}:
            raise SettingsError(f"未知健康组件: {component}")
        settings = self.effective_settings()
        health = self._load_health(settings)
        health["schema_version"] = "setup-health-v1"
        health["fingerprint"] = self._health_fingerprint(settings)
        health[component] = bool(healthy)
        write_json_atomic(self.health_path, health)

    def _load_health(self, settings: dict[str, Any]) -> dict[str, Any]:
        health = read_json_optional(self.health_path)
        if not isinstance(health, dict):
            return {}
        if health.get("fingerprint") != self._health_fingerprint(settings):
            return {}
        return health

    def _health_fingerprint(self, settings: dict[str, Any]) -> str:
        payload = {
            "ocr": settings.get("ocr", {}),
            "vision": {
                key: value
                for key, value in settings.get("vision", {}).items()
                if key != "api_key"
            },
            "api_key_sha256": hashlib.sha256(
                str(settings.get("vision", {}).get("api_key", "")).encode("utf-8")
            ).hexdigest(),
        }
        serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _invalidate_health(self) -> None:
        if self.health_path.exists():
            self.health_path.unlink()

    def _load_secret(self) -> str:
        if not self.secrets_path.exists():
            return ""
        for line in self.secrets_path.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() == "VISION_API_KEY":
                return value.strip()
        return ""

    @staticmethod
    def _validate(settings: dict[str, Any]) -> None:
        errors = list(
            Draft202012Validator(load_schema_file("settings-v1.schema.json")).iter_errors(
                settings
            )
        )
        if errors:
            raise SettingsError(errors[0].message)
