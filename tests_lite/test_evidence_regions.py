from __future__ import annotations

import hashlib

import pytest
from PIL import Image

from lite_app.evidence_regions import (
    generate_formula_evidence,
    resolve_formula_region,
    validate_normalized_bbox,
    validate_page_model_bboxes,
    verified_evidence_path,
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
        "recognition_run_id": "run-1",
        "images": [{"source": "source/page.jpg"}],
    }
    final["recognition_run_id"] = "run-1"

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
    assert manifest["recognition_run_id"] == "run-1"
    assert entry["source_path"] == "source/page.jpg"
    assert entry["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert entry["crop_sha256"] == hashlib.sha256(crop.read_bytes()).hexdigest()
    assert entry["locator_source"] == "hybrid"
    assert entry["pixel_bbox"][2] > entry["pixel_bbox"][0]
    assert (job_dir / "review" / "evidence_regions.json").is_file()
    assert ".." not in entry["crop_path"]


def test_evidence_uses_the_same_90cw_orientation_as_recognition(tmp_path):
    job_dir = tmp_path / "job-rotated"
    source = job_dir / "source" / "page.png"
    source.parent.mkdir(parents=True)
    image = Image.new("RGB", (200, 100), "blue")
    for x in range(100):
        for y in range(100):
            image.putpixel((x, y), (255, 0, 0))
    image.save(source)
    final = make_review_final("job-rotated")
    final["recognition_run_id"] = "run-rotated"
    formula = final["pages"][0]["product_sections"][0]["formulas"][0]
    formula["record_bbox"] = [0.0, 0.0, 1.0, 0.5]
    page = OCRPage(
        image_index=1,
        width=100,
        height=200,
        tokens=[],
        average_confidence=0.9,
        provider="test",
        model="test",
        elapsed_ms=1,
    )
    job = {
        "id": "job-rotated",
        "recognition_run_id": "run-rotated",
        "images": [{"source": "source/page.png", "rotation": "90cw"}],
    }

    manifest = generate_formula_evidence(job_dir, job, final, [page], {})
    entry = manifest["formulas"][formula["formula_id"]]
    oriented = Image.open(job_dir / entry["oriented_source_path"])
    crop = Image.open(job_dir / entry["crop_path"])

    assert oriented.size == (100, 200)
    assert crop.getpixel((crop.width // 2, crop.height // 2))[0] > 200


def test_page_model_bboxes_reject_reversed_and_heavily_overlapping_regions():
    reversed_formulas = [
        {"formula_id": "a", "source_order": 1, "record_bbox": [0.1, 0.6, 0.9, 0.9]},
        {"formula_id": "b", "source_order": 2, "record_bbox": [0.1, 0.1, 0.9, 0.4]},
    ]
    overlapping_formulas = [
        {"formula_id": "a", "source_order": 1, "record_bbox": [0.1, 0.1, 0.9, 0.6]},
        {"formula_id": "b", "source_order": 2, "record_bbox": [0.12, 0.12, 0.88, 0.58]},
    ]

    assert validate_page_model_bboxes(reversed_formulas) == {"a": None, "b": None}
    assert validate_page_model_bboxes(overlapping_formulas) == {"a": None, "b": None}


def test_manifest_entry_cannot_be_rebound_to_another_formula(tmp_path):
    job_dir = tmp_path / "job-binding"
    source = job_dir / "source" / "page.jpg"
    source.parent.mkdir(parents=True)
    Image.new("RGB", (600, 800), "white").save(source)
    final = make_review_final("job-binding")
    final["recognition_run_id"] = "run-binding"
    first = final["pages"][0]["product_sections"][0]["formulas"][0]
    second = dict(first)
    second["formula_id"] = "job-binding__page_001__formula_002"
    second["formula_sequence"] = 2
    second["source_order"] = 2
    final["pages"][0]["product_sections"][0]["formulas"].append(second)
    page = OCRPage(
        image_index=1,
        width=600,
        height=800,
        tokens=[],
        average_confidence=0.9,
        provider="test",
        model="test",
        elapsed_ms=1,
    )
    job = {
        "id": "job-binding",
        "recognition_run_id": "run-binding",
        "images": [{"source": "source/page.jpg", "rotation": "0"}],
    }
    manifest = generate_formula_evidence(job_dir, job, final, [page], {})
    first_id = first["formula_id"]
    second_id = second["formula_id"]
    manifest["formulas"][first_id], manifest["formulas"][second_id] = (
        manifest["formulas"][second_id],
        manifest["formulas"][first_id],
    )
    from lite_app.storage import write_json_atomic

    write_json_atomic(job_dir / "review" / "evidence_regions.json", manifest)

    assert verified_evidence_path(
        job_dir, first_id, job=job, final=final
    ) is None


def test_layout_record_is_used_when_model_bbox_is_missing(tmp_path):
    job_dir = tmp_path / "job-layout"
    source = job_dir / "source" / "page.jpg"
    source.parent.mkdir(parents=True)
    Image.new("RGB", (1000, 1000), "white").save(source)
    final = make_review_final("job-layout")
    final["recognition_run_id"] = "run-layout"
    formula = final["pages"][0]["product_sections"][0]["formulas"][0]
    formula["record_bbox"] = None
    page = OCRPage(
        image_index=1,
        width=1000,
        height=1000,
        tokens=[],
        average_confidence=0.9,
        provider="test",
        model="test",
        elapsed_ms=1,
    )
    job = {
        "id": "job-layout",
        "recognition_run_id": "run-layout",
        "images": [{"source": "source/page.jpg", "rotation": "0"}],
    }
    layout = {"1": {"lines": [], "records": [{"bbox": [100, 600, 900, 850]}]}}

    manifest = generate_formula_evidence(job_dir, job, final, [page], layout)
    entry = manifest["formulas"][formula["formula_id"]]

    assert entry["locator_source"] == "local"
    assert entry["normalized_bbox"][1] >= 0.55


def test_single_coarse_layout_record_does_not_replace_multiple_formula_slots(tmp_path):
    job_dir = tmp_path / "job-coarse-layout"
    source = job_dir / "source" / "page.jpg"
    source.parent.mkdir(parents=True)
    Image.new("RGB", (1000, 1000), "white").save(source)
    final = make_review_final("job-coarse-layout")
    final["recognition_run_id"] = "run-coarse"
    first = final["pages"][0]["product_sections"][0]["formulas"][0]
    first["record_bbox"] = None
    second = dict(first)
    second["formula_id"] = "job-coarse-layout__page_001__formula_002"
    second["formula_sequence"] = 2
    final["pages"][0]["product_sections"][0]["formulas"].append(second)
    page = OCRPage(
        image_index=1,
        width=1000,
        height=1000,
        tokens=[_token("content", "text", [100, 100, 900, 900])],
        average_confidence=0.9,
        provider="test",
        model="test",
        elapsed_ms=1,
    )
    job = {
        "id": "job-coarse-layout",
        "recognition_run_id": "run-coarse",
        "images": [{"source": "source/page.jpg", "rotation": "0"}],
    }
    layout = {"1": {"lines": [], "records": [{"bbox": [100, 100, 900, 900]}]}}

    manifest = generate_formula_evidence(job_dir, job, final, [page], layout)
    first_box = manifest["formulas"][first["formula_id"]]["normalized_bbox"]
    second_box = manifest["formulas"][second["formula_id"]]["normalized_bbox"]

    assert (first_box[1] + first_box[3]) / 2 < (second_box[1] + second_box[3]) / 2


def test_circled_formula_number_does_not_match_repeated_single_digit_amounts(tmp_path):
    job_dir = tmp_path / "job-numeric-anchors"
    source = job_dir / "source" / "page.jpg"
    source.parent.mkdir(parents=True)
    Image.new("RGB", (1000, 1000), "white").save(source)
    final = make_review_final("job-numeric-anchors")
    final["recognition_run_id"] = "run-numeric"
    first = final["pages"][0]["product_sections"][0]["formulas"][0]
    first["formula_no"] = "①"
    first["record_bbox"] = None
    second = dict(first)
    second["formula_id"] = "job-numeric-anchors__page_001__formula_002"
    second["formula_no"] = "②"
    second["formula_sequence"] = 2
    final["pages"][0]["product_sections"][0]["formulas"].append(second)
    page = OCRPage(
        image_index=1,
        width=1000,
        height=1000,
        tokens=[
            _token("top", "1", [100, 100, 150, 140]),
            _token("middle", "2", [100, 450, 150, 490]),
            _token("bottom", "1", [100, 850, 150, 890]),
        ],
        average_confidence=0.9,
        provider="test",
        model="test",
        elapsed_ms=1,
    )
    job = {
        "id": "job-numeric-anchors",
        "recognition_run_id": "run-numeric",
        "images": [{"source": "source/page.jpg", "rotation": "0"}],
    }
    layout = {
        "1": {
            "records": [],
            "lines": [
                {"text": "1 amount", "bbox": [100, 100, 300, 140]},
                {"text": "2 amount", "bbox": [100, 450, 300, 490]},
                {"text": "1 amount", "bbox": [100, 850, 300, 890]},
            ],
        }
    }

    manifest = generate_formula_evidence(job_dir, job, final, [page], layout)
    first_box = manifest["formulas"][first["formula_id"]]["normalized_bbox"]
    second_box = manifest["formulas"][second["formula_id"]]["normalized_bbox"]

    assert first_box[3] < 0.65
    assert second_box[1] > 0.35


def test_new_recognition_run_invalidates_previous_evidence(tmp_path):
    from lite_app.evidence_regions import invalidate_formula_evidence

    manifest_path = tmp_path / "review" / "evidence_regions.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        '{"schema_version":2,"recognition_run_id":"old","formulas":{"old":{}}}',
        encoding="utf-8",
    )

    invalidate_formula_evidence(tmp_path, "new")

    import json

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["recognition_run_id"] == "new"
    assert manifest["formulas"] == {}


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
