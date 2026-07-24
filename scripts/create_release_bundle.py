"""Build source bundle and SHA-256 checksum for a saved release version."""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}
INSTALL_WITH_AI = """daily-record-ocr-lite AI 安装入口

把本 Release 或仓库链接交给你的 AI，并要求它：

1. 读取根目录 AGENTS.md 和 docs/AI_AGENT_INSTALL.md；
2. 按操作系统安装核心依赖与真实 PP-OCRv6；
3. 运行 doctor、real_ocr 和应用 health 验收；
4. 协助在 /setup 或 CLI 配置你自己的视觉模型；
5. 禁止把 Mock/Demo 结果冒充真实识别。

仓库：https://github.com/liumingyang-maker/daily-record-ocr-lite
"""


def create_bundle(output_dir: Path, version: str = "1.0.0") -> tuple[Path, ...]:
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle = output_dir / f"daily-record-ocr-lite-v{version}-source.zip"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in _source_files():
            relative = path.relative_to(ROOT)
            if (
                not path.is_file()
                or any(part in EXCLUDED_PARTS for part in relative.parts)
                or relative.parts[:1] == ("data",)
                or relative.parts[:1] == ("dist",)
                or relative == Path(".env")
            ):
                continue
            archive.write(path, Path(f"daily-record-ocr-lite-v{version}") / relative)
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    checksum = output_dir / "SHA256SUMS.txt"
    checksum.write_text(f"{digest}  {bundle.name}\n", encoding="utf-8")
    install = output_dir / "INSTALL_WITH_AI.txt"
    install.write_text(INSTALL_WITH_AI, encoding="utf-8")
    release_notes = output_dir / "RELEASE_NOTES.md"
    release_notes.write_text(
        (ROOT / "docs" / "RELEASE_NOTES_V1.0.0.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return bundle, checksum, install, release_notes


def _source_files() -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    if completed.returncode == 0:
        names = completed.stdout.decode("utf-8").split("\0")
        return sorted(ROOT / name for name in names if name)
    return sorted(path for path in ROOT.rglob("*") if path.is_file())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--version", default="1.0.0")
    args = parser.parse_args(argv)
    for artifact in create_bundle(args.output_dir, args.version):
        print(artifact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
