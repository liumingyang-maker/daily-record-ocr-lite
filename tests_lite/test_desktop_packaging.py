import hashlib
import json
from pathlib import Path

import yaml


def test_artifact_names_separate_unsigned_tests_from_formal_assets():
    from scripts.build_desktop import artifact_name

    assert artifact_name("1.2.3", "windows", formal=True) == (
        "daily-record-ocr-lite-v1.2.3-windows-x64-setup.exe"
    )
    assert artifact_name("1.2.3", "macos", formal=True) == (
        "daily-record-ocr-lite-v1.2.3-macos-arm64.dmg"
    )
    assert "UNSIGNED" in artifact_name("1.2.3", "windows", formal=False)
    assert "UNSIGNED" in artifact_name("1.2.3", "macos", formal=False)


def test_checksum_and_provenance_are_reproducible_metadata(tmp_path: Path):
    from scripts.build_desktop import write_build_metadata

    artifact = tmp_path / "installer.exe"
    artifact.write_bytes(b"desktop-installer")

    checksums, provenance = write_build_metadata(
        [artifact],
        output_dir=tmp_path,
        git_sha="abc123",
        platform_name="windows",
        architecture="x64",
    )

    digest = hashlib.sha256(b"desktop-installer").hexdigest()
    assert checksums.read_text(encoding="utf-8") == f"{digest}  installer.exe\n"
    payload = json.loads(provenance.read_text(encoding="utf-8"))
    assert payload["git_sha"] == "abc123"
    assert payload["artifacts"] == [{"name": "installer.exe", "sha256": digest}]


def test_formal_release_gate_blocks_missing_signing_secrets():
    from scripts.build_desktop import formal_release_gate

    windows = formal_release_gate("windows", environment={})
    macos = formal_release_gate("macos", environment={})

    assert windows["ready"] is False
    assert windows["missing"] == ["WINDOWS_SIGN_CERT_BASE64", "WINDOWS_SIGN_CERT_PASSWORD"]
    assert macos["ready"] is False
    assert "APPLE_DEVELOPER_ID" in macos["missing"]
    assert "APPLE_NOTARY_PASSWORD" in macos["missing"]


def test_packaging_definitions_use_onedir_and_preserve_user_data():
    root = Path(__file__).resolve().parents[1]
    spec = (root / "packaging" / "desktop" / "daily_record_ocr.spec").read_text(encoding="utf-8")
    windows = (root / "packaging" / "windows" / "setup.iss").read_text(encoding="utf-8")
    macos = (root / "packaging" / "macos" / "build_dmg.sh").read_text(encoding="utf-8")

    assert "COLLECT(" in spec
    assert "config" in spec and "lite_app/templates" in spec and "lite_app/static" in spec
    assert "collect_data_files" in spec
    assert "copy_metadata" in spec
    assert '"opencv-contrib-python"' in spec
    assert '"python-bidi"' in spec
    assert "PrivilegesRequired=lowest" in windows
    assert "uninsdelete" not in windows.lower()
    assert "hdiutil create" in macos
    assert "Applications" in macos


def test_native_workflows_require_frozen_health_real_ocr_and_formal_secrets():
    root = Path(__file__).resolve().parents[1]
    test_build_path = root / ".github" / "workflows" / "desktop-build.yml"
    release_path = root / ".github" / "workflows" / "desktop-release-gate.yml"
    test_build = test_build_path.read_text(encoding="utf-8")
    release = release_path.read_text(encoding="utf-8")

    assert yaml.safe_load(test_build)
    assert yaml.safe_load(release)
    assert "windows-latest" in test_build and "macos-14" in test_build
    assert '"--smoke-test", "--install-models", "--ocr-test"' in test_build
    assert "--ocr-test" in test_build
    assert "APPLE_NOTARY_PASSWORD" in release
    assert "WINDOWS_SIGN_CERT_BASE64" in release
    assert "gh release" not in release.lower()
