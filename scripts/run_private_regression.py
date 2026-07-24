"""Run local private-image regression without adding private data to Git."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--golden", type=Path, required=True)
    args = parser.parse_args(argv)
    images = [
        path
        for path in args.images.iterdir()
        if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    ]
    if not images:
        print(json.dumps({"status": "ERROR", "message": "没有测试图片"}))
        return 2
    if not args.golden.exists():
        print(json.dumps({"status": "ERROR", "message": "golden 文件不存在"}))
        return 2
    print(
        json.dumps(
            {
                "status": "READY_TO_RUN",
                "image_count": len(images),
                "golden": str(args.golden),
                "message": "私有回归须在已配置真实 OCR/Vision 的本机任务流中执行。",
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
