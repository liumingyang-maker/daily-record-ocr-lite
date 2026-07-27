from __future__ import annotations

import importlib

import pytest


def test_per_image_rotations_are_validated_and_addressed_by_index():
    upload_options = importlib.import_module("lite_app.upload_options")

    rotations = upload_options.normalize_rotations(
        '["90cw", "auto"]', count=2, fallback="auto"
    )
    job = {"rotation": "auto", "rotations": rotations}

    assert upload_options.rotation_for_image(job, 1) == "90cw"
    assert upload_options.rotation_for_image(job, 2) == "auto"


def test_rotation_count_must_match_images():
    upload_options = importlib.import_module("lite_app.upload_options")

    with pytest.raises(ValueError, match="图片数量"):
        upload_options.normalize_rotations('["auto"]', count=2, fallback="auto")


def test_rotation_value_must_be_supported():
    upload_options = importlib.import_module("lite_app.upload_options")

    with pytest.raises(ValueError, match="无效"):
        upload_options.normalize_rotations('["sideways"]', count=1, fallback="auto")


def test_legacy_job_keeps_single_rotation():
    upload_options = importlib.import_module("lite_app.upload_options")

    assert upload_options.rotation_for_image({"rotation": "180"}, 3) == "180"
