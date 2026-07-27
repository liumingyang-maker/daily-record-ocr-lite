"""Versioned, resumable and integrity-checked desktop OCR model packages."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
import tempfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

import httpx

from .platform_paths import RESOURCE_ROOT

ProgressCallback = Callable[[dict[str, object]], None]
Downloader = Callable[[str, Path, int, ProgressCallback], None]


class ModelPackageError(RuntimeError):
    """Base model-package failure."""


class ModelIntegrityError(ModelPackageError):
    """A package or extracted model failed integrity validation."""


def load_model_manifest(path: Path | None = None) -> dict[str, Any]:
    manifest_path = path or RESOURCE_ROOT / "config" / "desktop-models.json"
    payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != "desktop-models-v1":
        raise ModelPackageError("不支持的桌面模型清单版本")
    packages = payload.get("packages")
    if not isinstance(packages, list) or not packages:
        raise ModelPackageError("桌面模型清单为空")
    return payload


def model_package_status(
    data_root: Path,
    *,
    manifest: dict[str, Any] | None = None,
) -> dict[str, object]:
    manifest_data = manifest or load_model_manifest()
    official_models = _official_models_root(Path(data_root))
    packages: list[dict[str, object]] = []
    for package in manifest_data["packages"]:
        ready = _verify_model_directory(official_models / package["name"], package)
        packages.append(
            {
                "name": package["name"],
                "ready": ready,
                "bytes": int(package["bytes"]),
            }
        )
    ready_count = sum(1 for package in packages if package["ready"])
    return {
        "status": "READY" if ready_count == len(packages) else "DOWNLOAD_REQUIRED",
        "ready_count": ready_count,
        "package_count": len(packages),
        "total_bytes": sum(int(package["bytes"]) for package in packages),
        "packages": packages,
    }


def install_model_packages(
    data_root: Path,
    *,
    manifest: dict[str, Any] | None = None,
    downloader: Downloader | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, object]:
    manifest_data = manifest or load_model_manifest()
    root = Path(data_root)
    official_models = _official_models_root(root)
    downloads = root / "models" / "downloads"
    official_models.mkdir(parents=True, exist_ok=True)
    downloads.mkdir(parents=True, exist_ok=True)
    progress_callback = progress or (lambda _event: None)
    download = downloader or _download_with_resume

    for index, package in enumerate(manifest_data["packages"], start=1):
        final_model = official_models / package["name"]
        if _verify_model_directory(final_model, package):
            progress_callback(
                {"state": "READY", "model": package["name"], "index": index}
            )
            continue
        archive_path = downloads / f"{package['name']}.tar.part"
        offset = archive_path.stat().st_size if archive_path.exists() else 0
        expected_bytes = int(package["bytes"])
        if offset > expected_bytes:
            archive_path.unlink()
            offset = 0
        progress_callback(
            {
                "state": "DOWNLOADING",
                "model": package["name"],
                "index": index,
                "package_count": len(manifest_data["packages"]),
                "downloaded_bytes": offset,
                "total_bytes": expected_bytes,
            }
        )
        def package_progress(event: dict[str, object]) -> None:
            progress_callback(
                {
                    "model": package["name"],
                    "index": index,
                    "package_count": len(manifest_data["packages"]),
                    "total_bytes": expected_bytes,
                    **event,
                }
            )

        if offset < expected_bytes:
            download(str(package["url"]), archive_path, offset, package_progress)
        if _sha256_file(archive_path) != package["sha256"]:
            archive_path.unlink(missing_ok=True)
            raise ModelIntegrityError(f"模型包校验失败: {package['name']}")
        _install_verified_archive(archive_path, final_model, package)
        archive_path.unlink(missing_ok=True)
        progress_callback({"state": "READY", "model": package["name"], "index": index})

    status = model_package_status(root, manifest=manifest_data)
    if status["status"] != "READY":
        raise ModelIntegrityError("模型文件安装后校验未通过")
    return status


def _official_models_root(data_root: Path) -> Path:
    return data_root / "models" / "paddlex" / "official_models"


def _download_with_resume(
    url: str,
    destination: Path,
    offset: int,
    progress: ProgressCallback,
) -> None:
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    with httpx.stream("GET", url, headers=headers, timeout=60, follow_redirects=False) as response:
        response.raise_for_status()
        append = offset > 0 and response.status_code == 206
        mode = "ab" if append else "wb"
        downloaded = offset if append else 0
        with destination.open(mode) as handle:
            for chunk in response.iter_bytes(1024 * 1024):
                handle.write(chunk)
                downloaded += len(chunk)
                progress({"state": "DOWNLOADING", "downloaded_bytes": downloaded})


def _install_verified_archive(
    archive_path: Path,
    final_model: Path,
    package: dict[str, Any],
) -> None:
    staging_parent = final_model.parent
    staging = Path(tempfile.mkdtemp(prefix=f".{final_model.name}-", dir=staging_parent))
    try:
        with tarfile.open(archive_path, mode="r:") as archive:
            members = archive.getmembers()
            for member in members:
                member_path = PurePosixPath(member.name)
                if (
                    member_path.is_absolute()
                    or ".." in member_path.parts
                    or member.issym()
                    or member.islnk()
                ):
                    raise ModelIntegrityError("模型包包含不安全路径")
            archive.extractall(staging, members=members)
        extracted = staging / package["archive_root"]
        if not _verify_model_directory(extracted, package):
            raise ModelIntegrityError(f"模型文件校验失败: {package['name']}")
        if final_model.exists():
            backup = final_model.with_name(f".{final_model.name}-invalid")
            if backup.exists():
                shutil.rmtree(backup)
            os.replace(final_model, backup)
        os.replace(extracted, final_model)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _verify_model_directory(path: Path, package: dict[str, Any]) -> bool:
    if not path.is_dir():
        return False
    expected = package.get("files", {})
    if not isinstance(expected, dict) or not expected:
        return False
    for relative, digest in expected.items():
        candidate = path / relative
        if not candidate.is_file() or _sha256_file(candidate) != digest:
            return False
    return True


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
