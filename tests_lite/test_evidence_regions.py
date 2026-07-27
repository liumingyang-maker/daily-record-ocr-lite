from __future__ import annotations

import hashlib

import pytest
from PIL import Image

from lite_app.evidence_regions import (
    generate_formula_evidence,
    resolve_formula_region,
    validate_normalized_bbox,
)
from lite_app.ocr.base import OCRPage, OCRToken
from tests_lite.review_fixtures import make_review_final


@pytest.mark.parametrize(
    "bbox",
    [
        None,
        [0.1, 0.2, 0.3],
        [-0.1, 0.2, 0.3, 0.4],
        [0.4, 0.2, 0.3, 0.5],
        [0.1, 0.1, 0.11, 0.11],
        [0.0, 0.0, 1.0, 1.0],
        [float("nan"), 0.1, 0.5, 0.5],
    ],
)
def test_validate_normalized_bbox_rejects_unsafe_values(bbox):
    assert validate_normalized_bbox(bbox) is None


def test_resolver_uses_safe_union_for_model_and_local_candidates():
    resolved = resolve_formula_region(
        [0.12, 0.20, 0.48, 0.48],
        [0.10, 0.18, 0.52, 0.55],
        content_bbox=[0.05, 0.05, 0.95, 0.95],
        padding=0.0,
    )

    assert resolved.source == "hybrid"
    assert resolved.normalized_bbox == [0.10, 0.18, 0.52, 0.55]


def test_resolver_falls_back_to_content_then_full_image():
    content = resolve_formula_region(
        None,
        None,
        content_bbox=[0.08, 0.10, 0.92, 0.90],
        padding=0.0,
    )
    full = resolve_formula_region(None, None, content_bbox=None, padding=0.0)

    assert content.source == "local"
    assert content.normalized_bbox == [0.08, 0.10, 0.92, 0.90]
    assert full.source == "full_image"
    assert full.normalized_bbox == [0.0, 0.0, 1.0, 1.0]


def test_generate_formula_evidence_binds_crop_to_source_and_hashes(tmp_path):
    job_dir = tmp_path / "20260727-220000-abcdef"
    source = job_dir / "source" / "page.jpg"
    source.parent.mkdir(parents=True)
    Image.new("RGB", (1000, 800), "white").save(source, quality=95)
    final = make_review_final("20260727-220000-abcdef")
    formula = final["pages"][0]["product_sections"][0]["formulas"][0]
    formula["formula_no"] = "配方1"
    formula["record_date"]["value"] = "24.7.19"
    formula["record_bbox"] = [0.1, 0.15, 0.85, 0.65]
    page = OCRPage(
        image_index=1,
        width=1000,
        height=800,
        tokens=[
            _token("p1_t001", "配方1", [120, 150, 220, 190]),
            _token("p1_t002", "24.7.19", [130, 200, 230, 235]),
            _token("p1_t003", "PA66", [150, 280, 250, 320]),
        ],
        average_confidence=0.9,
        provider="test",
        model="test",
        elapsed_ms=1,
    )
    job = {
        "id": "20260727-220000-abcdef",
        "images": [{"source": "source/page.jpg"}],
    }

    manifest = generate_formula_evidence(
        job_dir,
        job,
        final,
        [page],
        {"1": {"lines": [], "records": []}},
    )

    entry = manifest["formulas"][formula["formula_id"]]
    crop = job_dir / entry["crop_path"]
    assert crop.is_file()
    assert entry["source_image_index"] == 1
    assert entry["source_path"] == "source/page.jpg"
    assert entry["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert entry["crop_sha256"] == hashlib.sha256(crop.read_bytes()).hexdigest()
    assert entry["locator_source"] == "hybrid"
    assert entry["pixel_bbox"][2] > entry["pixel_bbox"][0]
    assert (job_dir / "review" / "evidence_regions.json").is_file()
    assert ".." not in entry["crop_path"]


def _token(token_id: str, text: str, bbox: list[float]) -> OCRToken:
    return OCRToken(
        id=token_id,
        text=text,
        confidence=0.9,
        polygon=[],
        bbox=bbox,
        center_x=(bbox[0] + bbox[2]) / 2,
        center_y=(bbox[1] + bbox[3]) / 2,
    )
