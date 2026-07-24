"""测试公共 fixtures。"""

import os
import tempfile

import pytest

# 设置测试环境变量（在导入 lite_app 之前）
_test_dir = tempfile.mkdtemp(prefix="ocr_test_")
os.environ["JOBS_DIR"] = os.path.join(_test_dir, "jobs")
os.environ["VISION_PROVIDER"] = "mock"
os.environ["OCR_PROVIDER"] = "mock"
os.environ["DEMO_MODE"] = "true"


@pytest.fixture(autouse=True)
def clean_config_cache():
    """每个测试前清除配置缓存。"""
    from lite_app.config import clear_config_cache
    clear_config_cache()
    yield
    clear_config_cache()


@pytest.fixture
def tmp_jobs_dir(tmp_path):
    """提供临时任务目录。"""
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    return jobs_dir


@pytest.fixture
def storage(tmp_jobs_dir):
    """提供使用临时目录的 JobStorage。"""
    from lite_app.storage import JobStorage
    return JobStorage(jobs_dir=tmp_jobs_dir)


@pytest.fixture
def sample_image(tmp_path):
    """生成一张小型测试图片。"""
    from PIL import Image
    img = Image.new("RGB", (100, 80), color=(255, 0, 0))
    path = tmp_path / "test_image.jpg"
    img.save(path, format="JPEG")
    return path


@pytest.fixture
def sample_image_rgba(tmp_path):
    """生成一张 RGBA 测试图片。"""
    from PIL import Image
    img = Image.new("RGBA", (100, 80), color=(255, 0, 0, 128))
    path = tmp_path / "test_rgba.png"
    img.save(path, format="PNG")
    return path


@pytest.fixture
def portrait_image(tmp_path):
    """生成一张竖图（高 > 宽）。"""
    from PIL import Image
    img = Image.new("RGB", (80, 200), color=(0, 0, 255))
    path = tmp_path / "portrait.jpg"
    img.save(path, format="JPEG")
    return path


@pytest.fixture
def large_image(tmp_path):
    """生成一张大图（超过 max_side）。"""
    from PIL import Image
    img = Image.new("RGB", (4000, 3000), color=(0, 255, 0))
    path = tmp_path / "large.jpg"
    img.save(path, format="JPEG")
    return path
