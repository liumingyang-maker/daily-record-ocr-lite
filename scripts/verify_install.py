"""验证安装是否完整。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def check_core_deps():
    """检查核心依赖。"""
    deps = {
        "fastapi": "fastapi",
        "uvicorn": "uvicorn",
        "jinja2": "jinja2",
        "httpx": "httpx",
        "yaml": "pyyaml",
        "PIL": "pillow",
        "openpyxl": "openpyxl",
        "jsonschema": "jsonschema",
        "rapidfuzz": "rapidfuzz",
        "numpy": "numpy",
    }
    missing = []
    for module, package in deps.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(package)
    return missing


def check_ocr_deps():
    """检查 OCR 依赖（可选）。"""
    deps = {
        "paddleocr": "paddleocr",
        "paddle": "paddlepaddle",
        "cv2": "opencv-python-headless",
    }
    missing = []
    for module, package in deps.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(package)
    return missing


def check_app_import():
    """检查应用能否导入。"""
    try:
        from lite_app.main import app
        return True, ""
    except Exception as e:
        return False, str(e)


def check_config():
    """检查配置文件是否存在。"""
    root = Path(__file__).resolve().parent.parent
    configs = [
        "config/app.yaml",
        "config/recognition.yaml",
        "config/record_schema.yaml",
        "config/fusion_rules.yaml",
        "config/export.yaml",
        "config/mock_result.json",
    ]
    missing = []
    for c in configs:
        if not (root / c).exists():
            missing.append(c)
    return missing


def main():
    print("=" * 50)
    print("daily-record-ocr-lite 安装验证")
    print("=" * 50)

    # 核心依赖
    missing_core = check_core_deps()
    if missing_core:
        print(f"\n[FAIL] 缺少核心依赖: {', '.join(missing_core)}")
        print("  运行: pip install -r requirements.txt")
    else:
        print("\n[OK] 核心依赖完整")

    # OCR 依赖
    missing_ocr = check_ocr_deps()
    if missing_ocr:
        print(f"\n[WARN] OCR 依赖未安装: {', '.join(missing_ocr)}")
        print("  运行: pip install -r requirements-ocr.txt")
        print("  （无 OCR 时系统降级运行，识别可靠性降低）")
    else:
        print("\n[OK] OCR 依赖完整（PP-OCRv6 可用）")

    # 应用导入
    ok, err = check_app_import()
    if ok:
        print("\n[OK] 应用导入成功")
    else:
        print(f"\n[FAIL] 应用导入失败: {err}")

    # 配置文件
    missing_cfg = check_config()
    if missing_cfg:
        print(f"\n[FAIL] 缺少配置文件: {', '.join(missing_cfg)}")
    else:
        print("\n[OK] 配置文件完整")

    print("\n" + "=" * 50)
    if missing_core or not ok or missing_cfg:
        print("验证未通过，请修复上述问题。")
        sys.exit(1)
    else:
        print("验证通过！可以启动: python -m app.main")
        sys.exit(0)


if __name__ == "__main__":
    main()
