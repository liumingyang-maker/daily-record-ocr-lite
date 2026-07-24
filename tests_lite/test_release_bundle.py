"""Release artifacts follow the v1.0.0 public asset contract."""

from __future__ import annotations

import zipfile
from pathlib import Path

from scripts import create_release_bundle


def test_release_bundle_contains_all_public_assets(tmp_path, monkeypatch):
    (tmp_path / "docs").mkdir()
    (tmp_path / "README.md").write_text("read me", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("agent protocol", encoding="utf-8")
    (tmp_path / "docs" / "RELEASE_NOTES_V1.0.0.md").write_text(
        "# Release notes\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(create_release_bundle, "ROOT", tmp_path)

    artifacts = create_release_bundle.create_bundle(tmp_path / "dist", "1.0.0")

    assert {path.name for path in artifacts} == {
        "daily-record-ocr-lite-v1.0.0-source.zip",
        "SHA256SUMS.txt",
        "INSTALL_WITH_AI.txt",
        "RELEASE_NOTES.md",
    }
    source_bundle = next(path for path in artifacts if path.suffix == ".zip")
    with zipfile.ZipFile(source_bundle) as archive:
        assert "daily-record-ocr-lite-v1.0.0/README.md" in archive.namelist()
    assert source_bundle.name in (tmp_path / "dist" / "SHA256SUMS.txt").read_text(
        "utf-8"
    )
    assert "AGENTS.md" in (tmp_path / "dist" / "INSTALL_WITH_AI.txt").read_text(
        "utf-8"
    )
    assert (tmp_path / "dist" / "RELEASE_NOTES.md").read_text("utf-8") == (
        "# Release notes\n"
    )


def test_release_publish_waits_for_every_release_gate():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    assert "needs: [core, real-ocr, windows-install]" in workflow
    assert "git merge-base --is-ancestor" in workflow
    assert "scripts/assert_junit_passed.py" in workflow
    assert "scripts\\doctor.py --json --gate" in workflow
    assert "softprops/action-gh-release@3bb12739c298aeb8a4eeaf626c5b8d85266b0e65" in workflow
