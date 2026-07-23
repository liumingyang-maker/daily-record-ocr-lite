"""集中配置模块：加载 .env、解析 YAML、支持环境变量占位。"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

# 项目根目录：lite_app/config.py -> 上一级
PROJECT_ROOT = Path(__file__).resolve().parent.parent

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _load_dotenv() -> None:
    """加载项目根目录下的 .env 文件（不覆盖已有环境变量）。"""
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def _substitute_env(value: str) -> str:
    """替换字符串中的 ${NAME} 和 ${NAME:-default} 占位符。"""

    def _replacer(m: re.Match) -> str:
        name = m.group(1)
        default = m.group(2) if m.group(2) is not None else ""
        return os.environ.get(name, default)

    return _ENV_PATTERN.sub(_replacer, value)


def _resolve_value(obj: Any) -> Any:
    """递归解析配置值中的环境变量占位。"""
    if isinstance(obj, str):
        return _substitute_env(obj)
    if isinstance(obj, dict):
        return {k: _resolve_value(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_value(item) for item in obj]
    return obj


class AppConfig:
    """应用配置对象。"""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    @property
    def host(self) -> str:
        return self._data["app"]["host"]

    @property
    def port(self) -> int:
        return int(self._data["app"]["port"])

    @property
    def jobs_dir(self) -> Path:
        p = Path(self._data["app"]["jobs_dir"])
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        return p

    @property
    def max_upload_mb(self) -> int:
        return int(self._data["app"]["max_upload_mb"])

    @property
    def allowed_extensions(self) -> list[str]:
        return self._data["app"]["allowed_extensions"]

    @property
    def preprocess(self) -> dict[str, Any]:
        return self._data["preprocess"]

    @property
    def vision(self) -> dict[str, Any]:
        return self._data["vision"]

    @property
    def schema_file(self) -> Path:
        p = Path(self._data["schema_file"])
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        return p

    @property
    def export_file(self) -> Path:
        p = Path(self._data["export_file"])
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        return p

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    """加载并缓存应用配置。"""
    _load_dotenv()
    config_path = PROJECT_ROOT / "config" / "app.yaml"
    if not config_path.exists():
        raise FileNotFoundError(
            f"配置文件不存在: {config_path}，请确认项目结构完整。"
        )
    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        raise ValueError(f"配置文件格式错误: {config_path}")
    data = _resolve_value(raw)
    _validate_config(data, config_path)
    return AppConfig(data)


_REQUIRED_FIELDS = [
    ("app", "host"),
    ("app", "port"),
    ("app", "jobs_dir"),
    ("app", "max_upload_mb"),
    ("app", "allowed_extensions"),
    ("preprocess", "max_side"),
    ("preprocess", "jpeg_quality"),
    ("vision", "provider"),
    ("vision", "model"),
    ("schema_file",),
    ("export_file",),
]


def _validate_config(data: dict[str, Any], config_path: Path) -> None:
    """校验必要配置字段，缺失时给出明确错误。"""
    for field_path in _REQUIRED_FIELDS:
        obj = data
        for key in field_path:
            if not isinstance(obj, dict) or key not in obj:
                dotted = ".".join(field_path)
                raise ValueError(
                    f"配置文件 {config_path} 缺少必要字段: {dotted}。"
                    f"请检查 config/app.yaml 是否完整。"
                )
            obj = obj[key]


def clear_config_cache() -> None:
    """清除配置缓存（测试用）。"""
    get_config.cache_clear()


def load_schema_config() -> dict[str, Any]:
    """加载 record_schema.yaml。"""
    cfg = get_config()
    path = cfg.schema_file
    if not path.exists():
        raise FileNotFoundError(f"Schema 配置文件不存在: {path}")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Schema 配置文件格式错误: {path}")
    return data


def load_export_config() -> dict[str, Any]:
    """加载 export.yaml。"""
    cfg = get_config()
    path = cfg.export_file
    if not path.exists():
        raise FileNotFoundError(f"导出配置文件不存在: {path}")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"导出配置文件格式错误: {path}")
    return data


def load_recognition_config() -> dict[str, Any]:
    """加载 recognition.yaml。"""
    path = PROJECT_ROOT / "config" / "recognition.yaml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        return {}
    return _resolve_value(raw)


def load_fusion_rules() -> dict[str, Any]:
    """加载 fusion_rules.yaml。"""
    path = PROJECT_ROOT / "config" / "fusion_rules.yaml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        return {}
    return data
