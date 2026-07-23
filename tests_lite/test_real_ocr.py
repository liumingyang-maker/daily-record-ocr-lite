"""真实 PP-OCRv6 测试（需要安装 paddleocr）。

运行: python -m pytest -m real_ocr -q
跳过: python -m pytest -m "not real_ocr" -q
"""

import pytest
from pathlib import Path

# 检查 paddleocr 是否可用
try:
    from paddleocr import PaddleOCR
    PADDLE_AVAILABLE = True
except ImportError:
    PADDLE_AVAILABLE = False

pytestmark = pytest.mark.real_ocr


@pytest.fixture
def sample_image(tmp_path):
    """生成一张包含文字的测试图片。"""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (400, 200), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    # 绘制一些文字
    try:
        font = ImageFont.truetype("arial.ttf", 24)
    except (OSError, IOError):
        font = ImageFont.load_default()
    draw.text((50, 30), "PA66  60kg", fill=(0, 0, 0), font=font)
    draw.text((50, 80), "GF30  30kg", fill=(0, 0, 0), font=font)
    draw.text((50, 130), "工艺: 50Hz", fill=(0, 0, 0), font=font)
    path = tmp_path / "test_ocr.jpg"
    img.save(path, format="JPEG")
    return path


@pytest.mark.skipif(not PADDLE_AVAILABLE, reason="PaddleOCR not installed")
class TestRealPaddleOCR:
    def test_provider_initialization(self):
        """测试 PaddleOCR 模型初始化。"""
        from lite_app.ocr.paddleocr_v6 import PaddleOCRv6Provider
        provider = PaddleOCRv6Provider(device="cpu", tier="medium")
        assert not provider.is_loaded
        provider.load()
        assert provider.is_loaded

    def test_recognize_returns_tokens(self, sample_image):
        """测试真实 OCR 识别返回 tokens。"""
        from lite_app.ocr.paddleocr_v6 import PaddleOCRv6Provider
        provider = PaddleOCRv6Provider(device="cpu", tier="medium")
        page = provider.recognize(sample_image)

        assert page.width > 0
        assert page.height > 0
        assert page.provider == "paddleocr_v6"
        assert len(page.tokens) > 0
        assert page.average_confidence > 0

        # 验证 token 结构
        for token in page.tokens:
            assert token.text
            assert 0 <= token.confidence <= 1
            assert len(token.bbox) == 4
            assert token.center_x > 0
            assert token.center_y > 0

    def test_model_singleton(self, sample_image):
        """测试模型只初始化一次。"""
        from lite_app.ocr.paddleocr_v6 import PaddleOCRv6Provider
        provider = PaddleOCRv6Provider(device="cpu", tier="medium")

        # 第一次识别触发加载
        page1 = provider.recognize(sample_image)
        assert provider.is_loaded

        # 第二次识别不应重新加载
        page2 = provider.recognize(sample_image)
        assert len(page2.tokens) > 0

    def test_overlay_generation(self, sample_image, tmp_path):
        """测试 overlay 图生成。"""
        from lite_app.ocr.paddleocr_v6 import PaddleOCRv6Provider
        from lite_app.ocr.overlay import generate_overlay

        provider = PaddleOCRv6Provider(device="cpu", tier="medium")
        page = provider.recognize(sample_image)

        overlay_path = tmp_path / "overlay.jpg"
        result = generate_overlay(sample_image, page, overlay_path)
        assert result.exists()
        assert result.stat().st_size > 0

    def test_performance(self, sample_image):
        """测试 OCR 性能（记录耗时）。"""
        import time
        from lite_app.ocr.paddleocr_v6 import PaddleOCRv6Provider

        provider = PaddleOCRv6Provider(device="cpu", tier="medium")

        # 首次加载
        t0 = time.time()
        provider.load()
        load_ms = int((time.time() - t0) * 1000)

        # 推理
        t0 = time.time()
        page = provider.recognize(sample_image)
        infer_ms = int((time.time() - t0) * 1000)

        print(f"\n  OCR 加载耗时: {load_ms}ms")
        print(f"  OCR 推理耗时: {infer_ms}ms")
        print(f"  检测到 {len(page.tokens)} 个文本框")
        print(f"  平均置信度: {page.average_confidence:.3f}")

        # 性能目标：推理 10 秒以内
        assert infer_ms < 10000, f"OCR 推理超时: {infer_ms}ms"
