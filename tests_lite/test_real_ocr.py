"""Real PP-OCRv6 inference Gate; never substitute mock output."""

from __future__ import annotations

import time

import pytest

try:
    import paddleocr  # noqa: F401

    PADDLE_AVAILABLE = True
except ImportError:
    PADDLE_AVAILABLE = False

pytestmark = pytest.mark.real_ocr


@pytest.fixture
def sample_image(tmp_path):
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (720, 260), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 42)
    except OSError:
        font = ImageFont.load_default()
    draw.text((40, 35), "PA66  60kg", fill="black", font=font)
    draw.text((40, 105), "GF30  30kg", fill="black", font=font)
    draw.text((40, 175), "Process 50Hz", fill="black", font=font)
    path = tmp_path / "test-real-ocr.png"
    image.save(path)
    return path


@pytest.fixture(scope="session")
def real_provider():
    from lite_app.ocr.paddleocr_v6 import PaddleOCRv6Provider

    provider = PaddleOCRv6Provider(device="cpu", tier="medium")
    provider.load()
    return provider


@pytest.mark.skipif(not PADDLE_AVAILABLE, reason="PaddleOCR not installed")
class TestRealPaddleOCR:
    def test_provider_initialization(self, real_provider):
        assert real_provider.is_loaded
        assert real_provider._model is not None

    def test_recognize_returns_real_tokens(self, sample_image, real_provider):
        page = real_provider.recognize(sample_image)
        assert page.provider == "paddleocr_v6"
        assert page.model == "PP-OCRv6_medium"
        assert page.width > 0 and page.height > 0
        assert page.tokens
        assert page.average_confidence > 0
        for token in page.tokens:
            assert token.text
            assert 0 <= token.confidence <= 1
            assert len(token.bbox) == 4
            assert token.center_x > 0
            assert token.center_y > 0

    def test_model_is_reused(self, sample_image, real_provider):
        model_id = id(real_provider._model)
        first = real_provider.recognize(sample_image)
        second = real_provider.recognize(sample_image)
        assert id(real_provider._model) == model_id
        assert first.tokens and second.tokens

    def test_overlay_generation(self, sample_image, tmp_path, real_provider):
        from lite_app.ocr.overlay import generate_overlay

        page = real_provider.recognize(sample_image)
        output = generate_overlay(sample_image, page, tmp_path / "overlay.jpg")
        assert output.exists()
        assert output.stat().st_size > 0

    def test_warm_inference_performance(self, sample_image, real_provider):
        started = time.monotonic()
        page = real_provider.recognize(sample_image)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        print(f"OCR 推理耗时: {elapsed_ms}ms; tokens={len(page.tokens)}")
        assert page.tokens
        assert elapsed_ms < 30_000, f"OCR 推理超时: {elapsed_ms}ms"
