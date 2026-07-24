"""Benchmark 脚本：测试识别准确率和性能。"""

import argparse
import json
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def run_benchmark(fixtures_dir: str) -> None:
    """运行 benchmark 测试。"""
    fixtures_path = Path(fixtures_dir)
    golden_file = fixtures_path / "golden_cases.yaml"

    if not golden_file.exists():
        print(f"未找到 golden_cases.yaml: {golden_file}")
        print("请在 tests/fixtures/private/ 下创建 golden_cases.yaml 和对应图片。")
        print()
        print("示例格式：")
        print("""
cases:
  - image: sample_01.jpg
    expected:
      records:
        - record_date: "24.7.10"
          title_contains: "PA66"
          materials:
            - name_contains: "PA66"
              amount: "60"
""")
        return

    import yaml
    with open(golden_file, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    cases = config.get("cases", [])
    if not cases:
        print("golden_cases.yaml 中没有测试用例。")
        return

    print(f"找到 {len(cases)} 个测试用例")
    print("=" * 60)

    results = {
        "total_cases": len(cases),
        "record_match": 0,
        "material_name_match": 0,
        "amount_exact_match": 0,
        "total_materials": 0,
        "total_amounts": 0,
    }

    for case in cases:
        image_name = case.get("image", "")
        image_path = fixtures_path / image_name
        if not image_path.exists():
            print(f"  [跳过] 图片不存在: {image_name}")
            continue

        expected = case.get("expected", {})
        print(f"  测试: {image_name}")

        # 这里可以集成真实 pipeline 调用
        # 当前只做结构验证
        print(f"    期望记录数: {len(expected.get('records', []))}")

    print()
    print("=" * 60)
    print("Benchmark 完成。")
    print("注意：完整 benchmark 需要配置真实 OCR 和视觉模型。")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="daily-record-ocr-lite benchmark")
    parser.add_argument(
        "--fixtures",
        default="tests/fixtures/private",
        help="测试 fixtures 目录",
    )
    args = parser.parse_args()
    run_benchmark(args.fixtures)
