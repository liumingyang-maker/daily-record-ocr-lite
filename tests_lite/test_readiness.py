"""The canonical READY gate must fail closed on every correctness condition."""

from __future__ import annotations

import copy
import json

from lite_app.contracts import normalize_legacy_result
from lite_app.final_result import FinalResultService, project_final_result
from lite_app.grouping.models import BusinessEntities
from lite_app.grouping.service import final_result_fingerprint
from lite_app.grouping.storage import save_business_entities
from lite_app.readiness import evaluate_content_gate, evaluate_ready_gate, iter_final_fields
from lite_app.storage import write_json_atomic


def _ready_case(storage):
    from lite_app.config import PROJECT_ROOT

    job = storage.create_job()
    job["images"] = [{"source": "source/source_01_test.jpg"}]
    job["demo_mode"] = False
    job["recognition_run_id"] = "run-1"
    job["ocr_engine"] = {
        "effective_provider": "paddleocr_v6",
        "loaded": True,
    }
    job["vision_engine"] = {
        "provider": "openai_compatible",
        "model": "vision-model",
        "healthy": True,
    }
    structured = normalize_legacy_result(
        json.loads((PROJECT_ROOT / "config" / "mock_result.json").read_text(encoding="utf-8")),
        job["id"],
    )
    final = project_final_result(job["id"], structured, {"fields": []})
    final["recognition_run_id"] = "run-1"
    final["pages"][0]["company"]["review_status"] = "AUTO_ACCEPT"
    for _, field in iter_final_fields(final):
        field["status"] = "MANUAL_CONFIRMED"
        field["review_status"] = "MANUAL_CONFIRMED"
    FinalResultService(storage.get_job_dir(job["id"])).replace(final)
    storage.save_job(job)
    return job, final


def test_ready_gate_requires_matching_finalization_receipt(storage):
    job, final = _ready_case(storage)
    job_dir = storage.get_job_dir(job["id"])
    content = evaluate_content_gate(job, final, job_dir)
    assert content.ready is True

    before_receipt = evaluate_ready_gate(job, final, job_dir)
    assert before_receipt.ready is False
    assert any("确认回执" in reason for reason in before_receipt.reasons)

    write_json_atomic(
        job_dir / "review" / "finalization.json",
        {"final_result_sha256": final_result_fingerprint(final)},
    )
    gate = evaluate_ready_gate(job, final, storage.get_job_dir(job["id"]))
    assert gate.ready is True
    assert gate.reasons == []

    final["updated_at"] = "changed"
    stale = evaluate_ready_gate(job, final, job_dir)
    assert stale.ready is False
    assert any("确认回执" in reason for reason in stale.reasons)


def test_ready_gate_rejects_demo_company_empty_and_unavailable_provider(storage):
    job, final = _ready_case(storage)
    cases = []

    demo_job = copy.deepcopy(job)
    demo_job["demo_mode"] = True
    cases.append((demo_job, final))

    company_final = copy.deepcopy(final)
    company_final["pages"][0]["company"]["review_status"] = "NEED_REVIEW"
    cases.append((job, company_final))

    empty_final = copy.deepcopy(final)
    next(iter_final_fields(empty_final))[1]["status"] = "EMPTY"
    cases.append((job, empty_final))

    broken_job = copy.deepcopy(job)
    broken_job["ocr_engine"]["loaded"] = False
    cases.append((broken_job, final))

    for candidate_job, candidate_final in cases:
        gate = evaluate_ready_gate(
            candidate_job,
            candidate_final,
            storage.get_job_dir(job["id"]),
        )
        assert gate.ready is False
        assert gate.reasons


def test_ready_gate_rejects_empty_or_stale_business_entities(storage):
    job, final = _ready_case(storage)
    job_dir = storage.get_job_dir(job["id"])

    save_business_entities(job_dir, BusinessEntities())
    empty_gate = evaluate_ready_gate(job, final, job_dir)
    assert empty_gate.ready is False
    assert any("BusinessEntities" in reason for reason in empty_gate.reasons)

    service = FinalResultService(job_dir)
    service.replace(final)
    stale = service.load()
    next(iter_final_fields(stale))[1]["value"] = "stale change"
    stale_gate = evaluate_ready_gate(job, stale, job_dir)
    assert stale_gate.ready is False
    assert any("BusinessEntities" in reason for reason in stale_gate.reasons)
