"""图片处理模块测试。"""


import pytest
from PIL import Image

from lite_app.image_utils import (
    ImageProcessError,
    prepare_image,
)


class TestPrepareImage:
    def test_rgb_image(self, sample_image, tmp_path):
        output = tmp_path / "out.jpg"
        info = prepare_image(sample_image, output, rotation="0")
        assert output.exists()
        img = Image.open(output)
        assert img.mode == "RGB"
        assert img.format == "JPEG"
        assert info["width"] == 100
        assert info["height"] == 80

    def test_rgba_to_rgb_white_bg(self, sample_image_rgba, tmp_path):
        output = tmp_path / "out.jpg"
        prepare_image(sample_image_rgba, output, rotation="0")
        assert output.exists()
        img = Image.open(output)
        assert img.mode == "RGB"
        assert img.format == "JPEG"

    def test_resize_large_image(self, large_image, tmp_path):
        output = tmp_path / "out.jpg"
        config = {"max_side": 2048}
        info = prepare_image(large_image, output, rotation="0", config=config)
        assert info["width"] <= 2048
        assert info["height"] <= 2048
        # 4000x3000 -> 2048x1536
        assert info["width"] == 2048
        assert info["height"] == 1536

    def test_no_upscale_small_image(self, sample_image, tmp_path):
        output = tmp_path / "out.jpg"
        config = {"max_side": 2048}
        info = prepare_image(sample_image, output, rotation="0", config=config)
        # 100x80 不应被放大
        assert info["width"] == 100
        assert info["height"] == 80

    def test_rotate_90cw(self, sample_image, tmp_path):
        output = tmp_path / "out.jpg"
        info = prepare_image(sample_image, output, rotation="90cw")
        # 100x80 顺时针90° -> 80x100
        assert info["width"] == 80
        assert info["height"] == 100

    def test_rotate_90ccw(self, sample_image, tmp_path):
        output = tmp_path / "out.jpg"
        info = prepare_image(sample_image, output, rotation="90ccw")
        # 100x80 逆时针90° -> 80x100
        assert info["width"] == 80
        assert info["height"] == 100

    def test_rotate_180(self, sample_image, tmp_path):
        output = tmp_path / "out.jpg"
        info = prepare_image(sample_image, output, rotation="180")
        # 180° 不改变尺寸
        assert info["width"] == 100
        assert info["height"] == 80

    def test_auto_rotate_portrait(self, portrait_image, tmp_path):
        output = tmp_path / "out.jpg"
        config = {
            "auto_rotate_portrait_to_landscape": True,
            "auto_landscape_direction": "ccw90",
        }
        info = prepare_image(portrait_image, output, rotation="auto", config=config)
        # 80x200 竖图 -> 旋转为横向 200x80
        assert info["width"] == 200
        assert info["height"] == 80

    def test_auto_no_rotate_landscape(self, sample_image, tmp_path):
        output = tmp_path / "out.jpg"
        config = {"auto_rotate_portrait_to_landscape": True}
        info = prepare_image(sample_image, output, rotation="auto", config=config)
        # 100x80 横图不旋转
        assert info["width"] == 100
        assert info["height"] == 80

    def test_output_is_jpeg(self, sample_image, tmp_path):
        output = tmp_path / "out.jpg"
        prepare_image(sample_image, output, rotation="0")
        img = Image.open(output)
        assert img.format == "JPEG"

    def test_non_image_file_raises(self, tmp_path):
        bad_file = tmp_path / "not_image.jpg"
        bad_file.write_text("this is not an image", encoding="utf-8")
        output = tmp_path / "out.jpg"
        with pytest.raises(ImageProcessError, match="不是可识别的图片"):
            prepare_image(bad_file, output, rotation="0")

    def test_rotation_direction_correctness(self, tmp_path):
        """验证旋转方向：左上角红色像素旋转后位置正确。"""
        # 创建 100x50 图片，左上角红色块（用块而非单像素避免 JPEG 压缩影响）
        img = Image.new("RGB", (100, 50), color=(255, 255, 255))
        # 画一个 5x5 红色块在左上角
        for x in range(5):
            for y in range(5):
                img.putpixel((x, y), (255, 0, 0))
        src = tmp_path / "dir_test.png"
        img.save(src, format="PNG")

        # 逆时针 90°：左上角 -> 左下角
        out_ccw = tmp_path / "ccw.jpg"
        prepare_image(src, out_ccw, rotation="90ccw")
        result = Image.open(out_ccw)
        # 50x100, 原左上区域 -> 逆时针90°后在左下区域
        assert result.size == (50, 100)
        pixel = result.getpixel((2, 97))
        assert pixel[0] > 100  # 红色通道明显高于其他

        # 顺时针 90°：左上角 -> 右上角
        out_cw = tmp_path / "cw.jpg"
        prepare_image(src, out_cw, rotation="90cw")
        result_cw = Image.open(out_cw)
        assert result_cw.size == (50, 100)
        pixel_cw = result_cw.getpixel((47, 2))
        assert pixel_cw[0] > 100  # 红色通道明显高于其他
