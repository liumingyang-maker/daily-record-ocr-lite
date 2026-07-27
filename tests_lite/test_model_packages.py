import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest


def _archive_bytes(*, unsafe: bool = False) -> bytes:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        content = b"verified-model"
        info = tarfile.TarInfo("../escape" if unsafe else "TestModel_infer/inference.bin")
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))
    return stream.getvalue()


def _manifest(archive: bytes) -> dict:
    return {
        "schema_version": "desktop-models-v1",
        "packages": [
            {
                "name": "TestModel",
                "archive_root": "TestModel_infer",
                "url": "https://example.test/TestModel.tar",
                "bytes": len(archive),
                "sha256": hashlib.sha256(archive).hexdigest(),
                "files": {"inference.bin": hashlib.sha256(b"verified-model").hexdigest()},
            }
        ],
    }


def test_install_resumes_partial_archive_and_verifies_extracted_files(tmp_path: Path):
    from lite_app.model_packages import install_model_packages, model_package_status

    archive = _archive_bytes()
    partial = tmp_path / "models" / "downloads" / "TestModel.tar.part"
    partial.parent.mkdir(parents=True)
    partial.write_bytes(archive[:100])

    def downloader(_url: str, destination: Path, offset: int, _progress):
        assert offset == 100
        with destination.open("ab") as handle:
            handle.write(archive[offset:])

    result = install_model_packages(tmp_path, manifest=_manifest(archive), downloader=downloader)

    assert result["status"] == "READY"
    assert (tmp_path / "models" / "paddlex" / "official_models" / "TestModel" / "inference.bin").exists()
    assert model_package_status(tmp_path, manifest=_manifest(archive))["status"] == "READY"


def test_corrupt_archive_never_replaces_final_model(tmp_path: Path):
    from lite_app.model_packages import ModelIntegrityError, install_model_packages

    archive = _archive_bytes()

    def downloader(_url: str, destination: Path, _offset: int, _progress):
        destination.write_bytes(b"corrupt")

    with pytest.raises(ModelIntegrityError):
        install_model_packages(tmp_path, manifest=_manifest(archive), downloader=downloader)

    assert not (tmp_path / "models" / "paddlex" / "official_models" / "TestModel").exists()
    assert not (tmp_path / "models" / "downloads" / "TestModel.tar.part").exists()


def test_unsafe_tar_member_is_rejected(tmp_path: Path):
    from lite_app.model_packages import ModelIntegrityError, install_model_packages

    archive = _archive_bytes(unsafe=True)

    def downloader(_url: str, destination: Path, _offset: int, _progress):
        destination.write_bytes(archive)

    with pytest.raises(ModelIntegrityError):
        install_model_packages(tmp_path, manifest=_manifest(archive), downloader=downloader)

    assert not (tmp_path.parent / "escape").exists()


def test_repository_manifest_has_version_hashes_and_https_urls():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "config" / "desktop-models.json").read_text(encoding="utf-8"))

    assert manifest["schema_version"] == "desktop-models-v1"
    assert {package["name"] for package in manifest["packages"]} == {
        "PP-LCNet_x1_0_textline_ori",
        "PP-OCRv6_medium_det",
        "PP-OCRv6_medium_rec",
    }
    for package in manifest["packages"]:
        assert package["url"].startswith("https://paddle-model-ecology.bj.bcebos.com/")
        assert len(package["sha256"]) == 64
        assert package["bytes"] > 0
        assert package["files"]


def test_desktop_gate_is_locked_until_verified_models_exist(tmp_path: Path):
    import lite_app.main as main

    main._model_ready_for_root.cache_clear()

    assert main._model_ready_for_root(str(tmp_path), "source") is True
    assert main._model_ready_for_root(str(tmp_path), "desktop") is False
