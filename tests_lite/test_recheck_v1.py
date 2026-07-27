"""Local OCR/VLM recheck closed-loop contracts."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from openpyxl import load_workbook
from PIL import Image

from lite_app.exporter import export_job
from lite_app.final_result import FinalResultService, project_final_result
from lite_app.grouping.service import final_result_fingerprint
from lite_app.ocr.base import OCRPage, OCRToken
from lite_app.readiness import iter_final_fields
from lite_app.review.recheck import RecheckError, crop_field_region, recheck_fields
from lite_app.storage import JobStorage, write_json_atomic


class FakeOCRManager:
    def __init__(self) -> None:
        self.colors: list[tuple[int, int, int]] = []
        self.paths: list[str] = []

    async def recognize_async(self, image_path: Path) -> OCRPage:
        self.paths.append(image_path.name)
        image = Image.open(image_path).convert("RGB")
        color = image.getpixel((image.width // 2, image.height // 2))
        self.colors.append(color)
        value = "0.15" if color[0] > color[2] else "0.25"
        token = OCRToken(
            id="local",
            text=value,
            confidence=0.98,
            polygon=[[0, 0], [10, 0], [10, 10], [0, 10]],
            bbox=[0, 0, 10, 10],
            center_x=5,
            center_y=5,
        )
        return OCRPage(1, image.width, image.height, [token], 0.98, "fake", "fake", 1)


class FakeVisionProvider:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values
        self.calls = 0
        self.image_counts: list[int] = []

    async def analyze(self, image_paths, system_prompt, user_prompt, json_schema):
        self.calls += 1
        self.image_counts.append(len(image_paths))
        return json.dumps(
            {
                "schema_version": "recheck-v1",
                "fields": [
                    {
                        "field_id": field_id,
                        "value": value,
                        "confidence": 0.97,
                    }
                    for field_id, value in self.values.items()
                ],
            }
        )


def _structured_two_pages() -> dict:
    root = Path(__file__).resolve().parents[1]
    first = json.loads((root / "config" / "mock_result.json").read_text("utf-8"))
    first_formula = first["pages"][0]["product_sections"][0]["formulas"][0]
    first_formula["formula_id"] = "job__page_001__formula_001"
    first_formula["materials"][0]["amount"]["value"] = "0.5"
    first_formula["materials"][0]["amount"]["bbox"] = [0.25, 0.25, 0.75, 0.75]

    second_page = copy.deepcopy(first["pages"][0])
    second_page["page_id"] = "page_002"
    second_page["source_image_index"] = 2
    second_formula = second_page["product_sections"][0]["formulas"][0]
    second_formula["formula_id"] = "job__page_002__formula_001"
    second_formula["materials"][0]["amount"]["value"] = "0.5"
    first["pages"].append(second_page)
    return first


def _prepare_job(tmp_path: Path):
    storage = JobStorage(tmp_path / "jobs")
    job = storage.create_job()
    job_dir = storage.get_job_dir(job["id"])
    red = job_dir / "page1.png"
    blue = job_dir / "page2.png"
    Image.new("RGB", (100, 80), "red").save(red)
    Image.new("RGB", (100, 80), "blue").save(blue)
    job["images"] = [
        {"source": red.name, "prepared_ocr": red.name},
        {"source": blue.name, "prepared_ocr": blue.name},
    ]
    job["demo_mode"] = False
    job["recognition_run_id"] = "recheck-run"
    job["ocr_engine"] = {
        "effective_provider": "paddleocr_v6",
        "loaded": True,
    }
    job["vision_engine"] = {
        "provider": "openai_compatible",
        "model": "vision-model",
        "healthy": True,
    }
    storage.save_job(job)

    structured = _structured_two_pages()
    for page in structured["pages"]:
        formula = page["product_sections"][0]["formulas"][0]
        formula["formula_id"] = formula["formula_id"].replace("job", job["id"], 1)
    ids = [
        (
            page["product_sections"][0]["formulas"][0]["formula_id"]
            + "__material_001__amount"
        )
        for page in structured["pages"]
    ]
    fusion = {
        "fields": [
            {
                "field_id": field_id,
                "field_type": "amount",
                "final_value": "0.15" if index == 0 else "0.25",
                "final_confidence": 0.55,
                "final_source": "conflict",
                "status": "CONFLICT",
                "bbox": [0.25, 0.25, 0.75, 0.75],
                "source_image_index": index + 1,
                "candidates": [
                    {"value": "0.5", "source": "vlm", "confidence": 0.9},
                    {
                        "value": "0.15" if index == 0 else "0.25",
                        "source": "ocr_base",
                        "confidence": 0.9,
                    },
                ],
            }
            for index, field_id in enumerate(ids)
        ]
    }
    final = project_final_result(job["id"], structured, fusion)
    final["recognition_run_id"] = "recheck-run"
    final["pages"][0]["company"]["review_status"] = "AUTO_ACCEPT"
    final["pages"][1]["company"]["review_status"] = "AUTO_ACCEPT"
    for field_id, field in iter_final_fields(final):
        if field_id not in ids:
            field["status"] = "MANUAL_CONFIRMED"
            field["review_status"] = "MANUAL_CONFIRMED"
    FinalResultService(job_dir).replace(final)
    write_json_atomic(job_dir / "fusion" / "result.json", fusion)
    return storage, job, ids


def test_normalized_bbox_crop_is_scaled_to_pixels(tmp_path: Path):
    source = tmp_path / "page.png"
    Image.new("RGB", (100, 80), "white").save(source)
    crops = crop_field_region(
        source, [0.25, 0.25, 0.75, 0.75], tmp_path / "crops", "field"
    )
    assert Image.open(crops["tight"]).size == (50, 40)


@pytest.mark.asyncio
async def test_batch_recheck_uses_correct_pages_one_vlm_call_and_updates_excel(
    tmp_path: Path,
):
    storage, job, field_ids = _prepare_job(tmp_path)
    ocr = FakeOCRManager()
    vision = FakeVisionProvider({field_ids[0]: "0.15", field_ids[1]: "0.25"})

    result = await recheck_fields(
        job["id"],
        storage.get_job_dir(job["id"]),
        job,
        field_ids,
        ocr,
        vision,
    )

    assert result["status"] == "RESOLVED"
    assert vision.calls == 1
    assert vision.image_counts == [4]
    assert all(path.endswith("_tight.jpg") for path in ocr.paths)
    assert ocr.colors[0][0] > ocr.colors[0][2]
    assert ocr.colors[1][2] > ocr.colors[1][0]

    final = FinalResultService(storage.get_job_dir(job["id"])).load()
    amounts = [
        page["product_sections"][0]["formulas"][0]["materials"][0]["amount"]
        for page in final["pages"]
    ]
    assert [field["value"] for field in amounts] == ["0.15", "0.25"]
    assert all(field["status"] == "AUTO_ACCEPT" for field in amounts)
    assert all(field["recheck_count"] == 1 for field in amounts)

    job = storage.get_job(job["id"])
    job["status"] = "READY"
    job["final_result_run_id"] = "recheck-run"
    storage.save_job(job)
    write_json_atomic(
        storage.get_job_dir(job["id"]) / "review" / "finalization.json",
        {"final_result_sha256": final_result_fingerprint(final)},
    )
    filename = export_job(job["id"], storage)
    workbook = load_workbook(storage.get_job_dir(job["id"]) / filename, data_only=True)
    assert workbook["配方明细"]["G2"].value == "0.15"
    assert workbook["配方明细"]["G3"].value == "0.25"


@pytest.mark.asyncio
async def test_second_recheck_is_rejected(tmp_path: Path):
    storage, job, field_ids = _prepare_job(tmp_path)
    ocr = FakeOCRManager()
    vision = FakeVisionProvider({field_ids[0]: "0.15"})
    await recheck_fields(
        job["id"], storage.get_job_dir(job["id"]), job, [field_ids[0]], ocr, vision
    )
    with pytest.raises(RecheckError, match="最多一次"):
        await recheck_fields(
            job["id"],
            storage.get_job_dir(job["id"]),
            job,
            [field_ids[0]],
            ocr,
            vision,
        )


@pytest.mark.asyncio
async def test_recheck_that_still_disagrees_remains_conflict(tmp_path: Path):
    storage, job, field_ids = _prepare_job(tmp_path)
    result = await recheck_fields(
        job["id"],
        storage.get_job_dir(job["id"]),
        job,
        [field_ids[0]],
        FakeOCRManager(),
        FakeVisionProvider({field_ids[0]: "0.5"}),
    )

    assert result["status"] == "REVIEW_REQUIRED"
    assert result["fields"][0]["status"] == "CONFLICT"
    final = FinalResultService(storage.get_job_dir(job["id"])).load()
    amount = final["pages"][0]["product_sections"][0]["formulas"][0]["materials"][0][
        "amount"
    ]
    assert amount["status"] == "CONFLICT"
    assert amount["recheck_count"] == 1


@pytest.mark.asyncio
async def test_recheck_without_bbox_fails_explicitly(tmp_path: Path):
    storage, job, field_ids = _prepare_job(tmp_path)
    final_service = FinalResultService(storage.get_job_dir(job["id"]))
    final = final_service.load()
    final["pages"][0]["product_sections"][0]["formulas"][0]["materials"][0][
        "amount"
    ]["bbox"] = None
    final_service.replace(final)
    with pytest.raises(RecheckError, match="bbox"):
        await recheck_fields(
            job["id"],
            storage.get_job_dir(job["id"]),
            job,
            [field_ids[0]],
            FakeOCRManager(),
            FakeVisionProvider({field_ids[0]: "0.15"}),
        )
