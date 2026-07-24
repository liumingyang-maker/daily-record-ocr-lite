"""Inspect or explicitly clear the cross-job recognition cache."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _stats(cache_root: Path) -> dict:
    result = {"root": str(cache_root), "ocr": 0, "vision": 0, "bytes": 0}
    for namespace in ("ocr", "vision"):
        directory = cache_root / namespace
        files = [path for path in directory.rglob("*.json") if path.is_file()]
        result[namespace] = len(files)
        result["bytes"] += sum(path.stat().st_size for path in files)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["stats", "clear"])
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT / "data" / "cache")
    args = parser.parse_args(argv)
    cache_root = args.root.resolve()
    if args.action == "stats":
        print(json.dumps(_stats(cache_root), ensure_ascii=False, indent=2))
        return 0
    if not args.yes:
        print("拒绝清理：请显式添加 --yes。")
        return 2
    expected_root = (ROOT / "data" / "cache").resolve()
    if cache_root != expected_root:
        print(f"拒绝清理：目标必须精确等于项目 data/cache：{expected_root}")
        return 2
    if cache_root.exists():
        shutil.rmtree(cache_root)
    (cache_root / "ocr").mkdir(parents=True)
    (cache_root / "vision").mkdir(parents=True)
    print(json.dumps({"cleared": str(cache_root)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
