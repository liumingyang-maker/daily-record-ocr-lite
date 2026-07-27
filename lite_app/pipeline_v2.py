"""Accuracy-first OCR + layout + vision + FinalResult pipeline."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .cache import FileRecognitionCache, compute_image_hash
from .config import (
    DATA_ROOT,
    PROJECT_ROOT,
    get_config,
    load_fusion_rules,
    load_recognition_config,
    load_schema_config,
)
from .contracts import (
    normalize_legacy_result,
    validate_page_coverage,
    validate_record_result,
)
from .evidence_regions import (
    generate_formula_evidence,
    invalidate_formula_evidence,
    resolve_page_formula_regions,
)
from .final_result import FinalResultService, project_final_result
from .fusion.association import (
    FieldEvidence,
    associate_field,
    record_boundary_mismatch,
)
from .fusion.date_recovery import recover_formula_date
from .fusion.engine import Candidate, FusedField, FusionEngine
from .image_utils_v2 import ImageProcessError, prepare_dual_images
from .knowledge.correction import (
    CorrectionCandidate,
    decide_correction,
)
from .knowledge.matcher import normalize_text
from .knowledge.path import resolve_knowledge_db_path
from .knowledge.retrieval import (
    KnowledgeRetrieval,
    RetrievalRequest,
)
from .layout.geometry import build_layout_evidence
from .ocr.base import OCRPage, OCRToken, scope_token_ids
from .ocr.manager import OCRModelManager, OCRUnavailableError
from .readiness import evaluate_ready_gate
from .settings import SettingsService
from .status import JobStatus
from .storage import JobStorage, write_json_atomic, write_text_atomic
from .upload_options import rotation_for_image
from .vision.base import VisionConfigurationError, VisionProviderError
from .vision.mock import MockVisionProvider
from .vision.openai_compatible import OpenAICompatibleVisionProvider

logger = logging.getLogger(__name__)


class PipelineError(RuntimeError):
    """A correctness-critical pipeline stage failed."""


class SchemaValidationError(PipelineError):
    """The structured vision result violates fatal record-v1 constraints."""


def build_vision_provider(vision_config: dict[str, Any]):
    provider_name = str(vision_config.get("provider", "")).strip()
    if provider_name == "mock":
        mock_path = Path(
            vision_config.get("mock_result", "config/mock_result.json")
        )
        if not mock_path.is_absolute():
            mock_path = PROJECT_ROOT / mock_path
        return MockVisionProvider(mock_path)
    if provider_name == "openai_compatible":
        if not vision_config.get("model"):
            raise VisionConfigurationError("视觉模型名称未配置")
        if not vision_config.get("api_key"):
            raise VisionConfigurationError("视觉模型 API Key 未配置")
        return OpenAICompatibleVisionProvider(vision_config)
    raise VisionConfigurationError("视觉模型尚未配置")


def extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        result = None
    if isinstance(result, dict):
        return result
    if isinstance(result, list):
        raise PipelineError("模型返回了 JSON 数组，但需要 JSON 对象")

    import re

    fence = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if fence:
        try:
            result = json.loads(fence.group(1).strip())
        except json.JSONDecodeError:
            result = None
        if isinstance(result, dict):
            return result

    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            result, _ = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            continue
        if isinstance(result, dict):
            return result
    raise PipelineError(f"无法从视觉模型响应解析 JSON: {text[:200]}")


async def analyze_job_v2(
    job_id: str,
    storage: JobStorage | None = None,
) -> dict[str, Any]:
    storage = storage or JobStorage()
    cfg = get_config()
    job = storage.get_job(job_id)
    job_dir = storage.get_job_dir(job_id)
    timings: dict[str, int] = {}
    demo_mode = _demo_mode()
    recognition_run_id = uuid.uuid4().hex

    try:
        job.update(
            {
                "error": "",
                "validation_errors": [],
                "demo_mode": demo_mode,
                "recognition_run_id": recognition_run_id,
                "final_result_run_id": None,
                "export_file": None,
                "status": JobStatus.PREPROCESSING,
                "status_message": "正在生成 OCR/Vision 双图...",
            }
        )
        storage.save_job(job)
        invalidate_formula_evidence(job_dir, recognition_run_id)

        started = time.time()
        vlm_paths: list[Path] = []
        ocr_paths: list[Path] = []
        for index, image in enumerate(job["images"], 1):
            source = job_dir / image["source"]
            vlm_path = job_dir / "preprocess" / f"page_{index:02d}_vision.jpg"
            ocr_path = job_dir / "preprocess" / f"page_{index:02d}_ocr.jpg"
            image_rotation = rotation_for_image(job, index)
            info = prepare_dual_images(
                source,
                vlm_path,
                ocr_path,
                rotation=image_rotation,
                config=cfg.preprocess,
            )
            image.update(
                {
                    "prepared": str(vlm_path.relative_to(job_dir)),
                    "prepared_vlm": str(vlm_path.relative_to(job_dir)),
                    "prepared_ocr": str(ocr_path.relative_to(job_dir)),
                    "width": info["vlm_width"],
                    "height": info["vlm_height"],
                    "rotation": image_rotation,
                }
            )
            vlm_paths.append(vlm_path)
            ocr_paths.append(ocr_path)
        timings["preprocess_ms"] = int((time.time() - started) * 1000)
        storage.save_job(job)

        recognition = load_recognition_config()
        ocr_config = dict(recognition.get("ocr", {}))
        ocr_config["enabled"] = _as_bool(ocr_config.get("enabled", True))
        manager = OCRModelManager()
        manager.configure(ocr_config)
        if ocr_config.get("provider") == "mock" and not demo_mode:
            raise OCRUnavailableError("Mock OCR 只能在用户显式启用演示模式后使用")

        job["status"] = JobStatus.OCR_RUNNING
        job["status_message"] = "正在运行 OCR..."
        storage.save_job(job)
        cache = FileRecognitionCache(PROJECT_ROOT / "data" / "cache")
        cache_enabled = _as_bool(recognition.get("cache", {}).get("enabled", True))
        cache_hits = {"ocr": 0, "vision": 0}
        ocr_pages: list[OCRPage] = []
        layout_by_page: dict[str, Any] = {}
        ocr_dir = job_dir / "ocr"
        layout_dir = job_dir / "layout"
        ocr_dir.mkdir(parents=True, exist_ok=True)
        layout_dir.mkdir(parents=True, exist_ok=True)

        started = time.time()
        for index, ocr_path in enumerate(ocr_paths, 1):
            ocr_key = _build_ocr_cache_key(
                ocr_path,
                rotation_for_image(job, index),
                cfg.preprocess,
                ocr_config,
                manager.get_status(),
            )
            page, cache_hit = await _recognize_with_cache(
                manager,
                cache,
                ocr_path,
                index,
                cache_enabled,
                ocr_key,
            )
            if cache_hit:
                cache_hits["ocr"] += 1
            ocr_pages.append(page)
            write_json_atomic(
                ocr_dir / f"page_{index:02d}_base.json",
                _ocr_page_to_dict(page),
            )

            page_layout = build_layout_evidence(page.tokens, page.height)
            layout_by_page[str(index)] = page_layout
            write_json_atomic(
                layout_dir / f"page_{index:02d}_lines.json",
                page_layout["lines"],
            )
            write_json_atomic(
                layout_dir / f"page_{index:02d}_pairs.json",
                page_layout["pairs"],
            )
            write_json_atomic(
                layout_dir / f"page_{index:02d}_records.json",
                page_layout["records"],
            )
            try:
                from .ocr.overlay import generate_overlay

                generate_overlay(
                    ocr_path,
                    page,
                    ocr_dir / f"page_{index:02d}_overlay.jpg",
                    show_token_id=True,
                )
            except Exception as exc:
                logger.warning("OCR overlay 生成失败（非关键）: %s", exc)
        timings["ocr_ms"] = int((time.time() - started) * 1000)

        vision_config = dict(cfg.vision)
        vision_config.update(
            SettingsService(DATA_ROOT).effective_settings()["vision"]
        )
        if vision_config.get("provider") == "mock" and not demo_mode:
            raise PipelineError("Mock Vision 只能在用户显式启用演示模式后使用")
        vision_provider = build_vision_provider(vision_config)
        job.update(
            {
                "provider": vision_config.get("provider", ""),
                "model": vision_config.get("model", ""),
                "ocr_engine": manager.get_status(),
            }
        )
        job["status"] = JobStatus.VISION_RUNNING
        job["status_message"] = "正在调用视觉模型..."
        storage.save_job(job)

        schema_config = load_schema_config()
        schema = schema_config["schema"]
        ocr_evidence = [page.to_evidence_json() for page in ocr_pages]
        layout_prompt = {
            page_index: {
                "lines": evidence["lines"],
                "pairs": evidence["pairs"],
                "records": evidence["records"],
            }
            for page_index, evidence in layout_by_page.items()
        }
        knowledge_enabled = _knowledge_assist_enabled()
        knowledge_prompt = (
            _build_knowledge_prompt(
                ocr_pages,
                _knowledge_db_path(),
            )
            if knowledge_enabled
            else {
                "policy": {"role": "disabled_for_ab_gate"},
                "references": [],
            }
        )
        job["knowledge_assist_enabled"] = knowledge_enabled
        compact_qwen = _uses_compact_qwen_contract(vision_config)
        if compact_qwen:
            system_prompt = (
                "你是中文手写配方录入员。以原图为准，OCR、布局和历史知识仅为"
                "辅助。不得猜测看不清的值。只返回 JSON 对象，不要 Markdown。"
            )
            user_prompt = _build_compact_qwen_prompt(
                instructions=schema_config.get("instructions", ""),
                ocr_evidence=ocr_evidence,
                layout_prompt=layout_prompt,
                knowledge_prompt=knowledge_prompt,
            )
        else:
            system_prompt = schema_config.get("system_prompt", "")
            user_prompt = (
                f"{schema_config.get('instructions', '')}\n\n"
                "以下 OCR 与本地布局仅为辅助证据，可能有误：\n"
                f"OCR={json.dumps(ocr_evidence, ensure_ascii=False)}\n"
                f"LAYOUT={json.dumps(layout_prompt, ensure_ascii=False)}\n"
                "以下知识候选仅用于核对文字名称，不是图片事实；"
                "新名称必须保留，数量、日期、配方号、编号和单位绝不按历史修改：\n"
                f"KNOWLEDGE={json.dumps(knowledge_prompt, ensure_ascii=False)}\n"
                "只返回严格符合 JSON Schema 的 JSON。"
            )
        vision_key = _hash_payload(
            {
                "images": [compute_image_hash(path) for path in vlm_paths],
                "provider": vision_config.get("provider"),
                "model": vision_config.get("model"),
                "endpoint": (
                    vision_config.get("base_url"),
                    vision_config.get("endpoint"),
                ),
                "prompt_version": schema_config.get("prompt_version"),
                "prompt": system_prompt + user_prompt,
                "contract": (
                    "compact-records-v1" if compact_qwen else "record-v1"
                ),
                "schema": schema,
                "ocr": ocr_evidence,
                "layout": layout_prompt,
                "knowledge": knowledge_prompt,
                "image_detail": vision_config.get("image_detail"),
                "extra_body": vision_config.get("extra_body", {}),
            }
        )
        started = time.time()
        cached_vision = (
            cache.get_json("vision", vision_key) if cache_enabled else None
        )
        vision_cache_hit = bool(
            cached_vision and isinstance(cached_vision.get("raw_response"), str)
        )
        if vision_cache_hit:
            raw_response = cached_vision["raw_response"]
            cache_hits["vision"] += 1
        else:
            raw_response = await vision_provider.analyze(
                vlm_paths,
                system_prompt,
                user_prompt,
                schema,
            )
            if cache_enabled:
                cache.put_json(
                    "vision",
                    vision_key,
                    {"raw_response": raw_response},
                )
        timings["vision_ms"] = int((time.time() - started) * 1000)
        vision_dir = job_dir / "vision"
        write_text_atomic(vision_dir / "raw_response.txt", raw_response)

        structured = normalize_legacy_result(extract_json(raw_response), job_id)
        write_json_atomic(vision_dir / "structured_result.json", structured)
        validation = validate_record_result(structured)
        validation.fatal.extend(
            validate_page_coverage(structured, expected_pages=len(job["images"]))
        )
        write_json_atomic(
            vision_dir / "schema_errors.json",
            [issue.to_dict() for issue in validation.issues],
        )
        job["validation_errors"] = [
            issue.to_dict() for issue in validation.issues
        ]
        if validation.fatal:
            job["status"] = JobStatus.FAILED_SCHEMA
            job["status_message"] = (
                f"视觉结果存在 {len(validation.fatal)} 个致命 Schema 错误"
            )
            storage.save_job(job)
            raise SchemaValidationError(job["status_message"])

        job["status"] = JobStatus.MATCHING_HISTORY
        job["status_message"] = "正在匹配历史知识..."
        storage.save_job(job)
        started = time.time()
        history = _history_candidates(structured) if knowledge_enabled else {}
        timings["history_ms"] = int((time.time() - started) * 1000)

        job["status"] = JobStatus.FUSING
        job["status_message"] = "正在融合 OCR/VLM/History/Layout..."
        storage.save_job(job)
        started = time.time()
        layout_association = {
            "pairs": {
                page_index: evidence["pairs"]
                for page_index, evidence in layout_by_page.items()
            },
            "records": {
                page_index: evidence["records"]
                for page_index, evidence in layout_by_page.items()
            },
            "formula_regions": _formula_regions_by_page(
                structured,
                ocr_pages,
                layout_by_page,
            ),
        }
        fusion = _build_fusion_result(
            structured,
            ocr_pages,
            history,
            layout_association,
        )
        timings["fusion_ms"] = int((time.time() - started) * 1000)
        write_json_atomic(job_dir / "fusion" / "candidates.json", fusion)
        write_json_atomic(job_dir / "fusion" / "result.json", fusion)

        final = project_final_result(job_id, structured, fusion)
        final["recognition_run_id"] = recognition_run_id
        final_service = FinalResultService(job_dir)
        final_service.replace(final)
        try:
            generate_formula_evidence(
                job_dir,
                job,
                final,
                ocr_pages,
                layout_by_page,
                cfg.preprocess,
            )
        except Exception:
            logger.warning("配方审查证据生成失败，审查页将回退显示整图")

        job["schema_status"] = (
            "REVIEW_REQUIRED" if validation.reviewable else "VALID"
        )
        job["cache_hits"] = cache_hits
        job["timings_ms"] = timings
        job["vision_engine"] = {
            "provider": vision_config.get("provider", ""),
            "model": vision_config.get("model", ""),
            "healthy": not demo_mode,
            "cache_hit": vision_cache_hit,
        }
        job["final_result_run_id"] = recognition_run_id
        gate = evaluate_ready_gate(job, final, job_dir)
        if gate.ready:
            job["status"] = JobStatus.READY
            job["status_message"] = "真实双引擎识别完成"
        else:
            job["status"] = JobStatus.REVIEW_REQUIRED
            job["status_message"] = "；".join(gate.reasons)
        storage.save_job(job)
        return job
    except SchemaValidationError:
        raise
    except (ImageProcessError, VisionProviderError, OCRUnavailableError, PipelineError) as exc:
        job["status"] = JobStatus.FAILED
        job["error"] = str(exc)
        job["status_message"] = str(exc)
        job["timings_ms"] = timings
        storage.save_job(job)
        raise
    except Exception as exc:
        job["status"] = JobStatus.FAILED
        job["error"] = f"未知错误: {exc}"
        job["status_message"] = job["error"]
        job["timings_ms"] = timings
        storage.save_job(job)
        logger.exception("任务 %s 失败", job_id)
        raise PipelineError(f"识别过程出错: {exc}") from exc


def _build_fusion_result(
    vlm_result: dict[str, Any],
    ocr_results: list[OCRPage],
    history_candidates: dict[str, list],
    layout: dict[str, Any] | None = None,
) -> dict[str, Any]:
    engine = FusionEngine(load_fusion_rules())
    fields: list[dict[str, Any]] = []

    for record in _extract_records_from_vlm(vlm_result):
        formula_id = str(
            record.get("formula_id") or record.get("record_id") or "formula"
        )
        image_index = int((record.get("source_image_indexes") or [1])[0])
        local_formula_region = (
            (layout or {})
            .get("formula_regions", {})
            .get(str(image_index), {})
            .get(formula_id)
        )
        record_bbox = local_formula_region or record.get("record_bbox")
        fields.append(
            _fuse_record_date(
                engine,
                formula_id,
                record.get("record_date", {}),
                image_index,
                ocr_results,
                layout,
            )
        )
        for material_index, material in enumerate(record.get("materials", []), 1):
            legacy_base = material.get("field_id")
            material_id = material.get(
                "material_id", f"material_{material_index:03d}"
            )
            base = legacy_base or f"{formula_id}__{material_id}"
            separator = "_" if legacy_base else "__"
            for field_name, field_type in (
                ("name", "text"),
                ("amount", "amount"),
                ("unit", "text"),
            ):
                field_id = f"{base}{separator}{field_name}"
                fields.append(
                    _fuse_one(
                        engine,
                        field_id,
                        field_type,
                        material.get(field_name, {}),
                        image_index,
                        record_bbox,
                        ocr_results,
                        history_candidates.get(field_id, []),
                        layout,
                        material.get("name", {}) if field_name == "amount" else None,
                        {
                            "name": "material",
                            "amount": "amount",
                            "unit": "unit",
                        }[field_name],
                    )
                )
        for parameter_index, parameter in enumerate(
            record.get("process_parameters", []), 1
        ):
            parameter_id = parameter.get(
                "parameter_id", f"parameter_{parameter_index:03d}"
            )
            base = f"{formula_id}__{parameter_id}"
            for field_name, field_type in (
                ("name", "text"),
                ("value", "amount"),
                ("unit", "text"),
            ):
                fields.append(
                    _fuse_one(
                        engine,
                        f"{base}__{field_name}",
                        field_type,
                        parameter.get(field_name, {}),
                        image_index,
                        record_bbox,
                        ocr_results,
                        [],
                        layout,
                        parameter.get("name", {}) if field_name == "value" else None,
                        {
                            "name": "process",
                            "value": "amount",
                            "unit": "unit",
                        }[field_name],
                    )
                )

    _reject_reused_numeric_tokens(engine, fields)
    summary = {
        "total_fields": len(fields),
        "auto_accept": sum(
            field["status"] == "AUTO_ACCEPT" for field in fields
        ),
        "conflict": sum(field["status"] == "CONFLICT" for field in fields),
        "need_review": sum(
            field["status"] == "NEED_REVIEW" for field in fields
        ),
    }
    return {
        "schema_version": "fusion-v1",
        "fields": fields,
        "summary": summary,
    }


def _formula_regions_by_page(
    vlm_result: dict[str, Any],
    ocr_results: list[OCRPage],
    layout_by_page: dict[str, Any],
) -> dict[str, dict[str, list[float] | None]]:
    pages_by_index = {page.image_index: page for page in ocr_results}
    result: dict[str, dict[str, list[float] | None]] = {}
    for structured_page in vlm_result.get("pages", []):
        image_index = int(structured_page.get("source_image_index", 1))
        page = pages_by_index.get(image_index)
        if page is None:
            continue
        formulas = [
            formula
            for section in structured_page.get("product_sections", [])
            for formula in section.get("formulas", [])
        ]
        result[str(image_index)] = resolve_page_formula_regions(
            formulas,
            page,
            layout_by_page.get(str(image_index), {}),
        )
    return result


def _fuse_record_date(
    engine: FusionEngine,
    formula_id: str,
    field_object: Any,
    image_index: int,
    ocr_results: list[OCRPage],
    layout: dict[str, Any] | None,
) -> dict[str, Any]:
    field_id = f"{formula_id}__record_date"
    value, confidence, evidence_ids, bbox = _extract_field_info(field_object)
    candidates: list[Candidate] = []
    association = None
    if value:
        candidates.append(
            Candidate(
                value=value,
                normalized_value=value,
                source="vlm",
                confidence=confidence,
                evidence=evidence_ids,
            )
        )
    else:
        page = next(
            (page for page in ocr_results if page.image_index == image_index),
            None,
        )
        if page is not None:
            association = recover_formula_date(
                formula_id=formula_id,
                vlm_value=value,
                page=page,
                formula_regions=(layout or {})
                .get("formula_regions", {})
                .get(str(image_index), {}),
            )
        if association is not None:
            candidates.append(
                Candidate(
                    value=association.value,
                    normalized_value=association.value,
                    source="ocr_base",
                    confidence=association.confidence,
                    evidence=association.token_ids,
                )
            )
    result = _fused_to_dict(engine.fuse_field(field_id, "date", candidates))
    result = _apply_knowledge_correction(result, "date", [])
    result["bbox"] = association.bbox if association is not None else bbox
    result["source_image_index"] = image_index
    if association is not None:
        result["status"] = "NEED_REVIEW"
        result["association"] = {
            "method": association.method,
            "score": association.association_score,
            "reasons": association.reasons,
        }
    return result


def _reject_reused_numeric_tokens(
    engine: FusionEngine,
    fields: list[dict[str, Any]],
) -> None:
    claims: dict[str, set[str]] = {}
    for field in fields:
        if field.get("field_type") not in {"amount", "numeric"}:
            continue
        for candidate in field.get("candidates", []):
            if not str(candidate.get("source", "")).startswith("ocr"):
                continue
            for token_id in candidate.get("evidence", []):
                claims.setdefault(str(token_id), set()).add(
                    str(field.get("field_id", ""))
                )
    reused = {
        token_id
        for token_id, field_ids in claims.items()
        if len(field_ids) > 1
    }
    if not reused:
        return
    for field in fields:
        ocr_evidence = {
            str(token_id)
            for candidate in field.get("candidates", [])
            if str(candidate.get("source", "")).startswith("ocr")
            for token_id in candidate.get("evidence", [])
        }
        if not ocr_evidence.intersection(reused):
            continue
        safe_candidates = [
            Candidate(
                value=str(candidate.get("value", "")),
                normalized_value=str(candidate.get("value", "")),
                source="vlm",
                confidence=float(candidate.get("confidence", 0.0)),
                evidence=list(candidate.get("evidence", [])),
            )
            for candidate in field.get("candidates", [])
            if candidate.get("source") == "vlm" and candidate.get("value")
        ]
        repaired = _fused_to_dict(
            engine.fuse_field(
                str(field.get("field_id", "")),
                str(field.get("field_type", "amount")),
                safe_candidates,
            )
        )
        repaired = _apply_knowledge_correction(
            repaired,
            str(field.get("field_type", "amount")),
            [],
        )
        repaired["status"] = "NEED_REVIEW"
        repaired.setdefault("reasons", []).append("OCR_NUMERIC_TOKEN_REUSED")
        repaired["bbox"] = None
        repaired["source_image_index"] = field.get("source_image_index", 1)
        field.clear()
        field.update(repaired)


def _fuse_one(
    engine: FusionEngine,
    field_id: str,
    field_type: str,
    field_object: Any,
    image_index: int,
    record_bbox: list[float] | None,
    ocr_results: list[OCRPage],
    history: list[Any],
    layout: dict[str, Any] | None,
    anchor_object: Any = None,
    knowledge_field_type: str | None = None,
) -> dict[str, Any]:
    value, confidence, evidence_ids, bbox = _extract_field_info(field_object)
    anchor_value, _, anchor_evidence_ids, anchor_bbox = _extract_field_info(
        anchor_object
    )
    candidates: list[Candidate] = []
    if value:
        candidates.append(
            Candidate(
                value=value,
                normalized_value=(
                    value if field_type == "amount" else normalize_text(value)
                ),
                source="vlm",
                confidence=confidence,
                evidence=evidence_ids,
            )
        )
    associations = associate_field(
        FieldEvidence(
            field_id=field_id,
            field_type=field_type,
            source_image_index=image_index,
            field_bbox=bbox,
            record_bbox=record_bbox,
            evidence_token_ids=evidence_ids,
            vlm_value=value,
            anchor_token_ids=anchor_evidence_ids,
            anchor_bbox=anchor_bbox,
            anchor_value=anchor_value,
        ),
        ocr_results,
        layout,
    )
    for association in associations:
        candidates.append(
            Candidate(
                value=association.value,
                normalized_value=(
                    association.value
                    if field_type == "amount"
                    else normalize_text(association.value)
                ),
                source="ocr_base",
                confidence=association.confidence,
                evidence=association.token_ids,
            )
        )
    fused = engine.fuse_field(field_id, field_type, candidates)
    result = _fused_to_dict(fused)
    result = _apply_knowledge_correction(
        result,
        knowledge_field_type or field_type,
        history,
    )
    result["bbox"] = associations[0].bbox if associations else bbox
    result["source_image_index"] = image_index
    if associations:
        result["association"] = {
            "method": associations[0].method,
            "score": associations[0].association_score,
            "reasons": associations[0].reasons,
        }
        if associations[0].requires_review:
            result["status"] = "NEED_REVIEW"
    if record_boundary_mismatch(image_index, record_bbox, ocr_results, layout):
        result["status"] = "NEED_REVIEW"
        result.setdefault("association", {}).setdefault("reasons", []).append(
            "RECORD_BOUNDARY_MISMATCH"
        )
    return result


def _knowledge_db_path() -> Path:
    return resolve_knowledge_db_path()


def _knowledge_assist_enabled() -> bool:
    return _as_bool(os.environ.get("KNOWLEDGE_ASSIST_ENABLED", "true"))


def _uses_compact_qwen_contract(vision_config: dict[str, Any]) -> bool:
    hostname = (
        urlparse(str(vision_config.get("base_url", ""))).hostname or ""
    ).lower()
    model = str(vision_config.get("model", "")).lower()
    return hostname.endswith(".aliyuncs.com") and model == "qwen3.7-plus"


def _build_compact_qwen_prompt(
    *,
    instructions: str,
    ocr_evidence: list[dict[str, Any]],
    layout_prompt: dict[str, Any],
    knowledge_prompt: dict[str, Any],
) -> str:
    del instructions
    compact_ocr = [
        {
            "image_index": page.get("image_index"),
            "tokens": [
                {
                    "id": token.get("id"),
                    "text": token.get("text"),
                    "confidence": token.get("confidence"),
                    "bbox": token.get("bbox"),
                }
                for token in page.get("ocr_tokens", page.get("tokens", []))
            ],
        }
        for page in ocr_evidence
    ]
    compact_layout = {
        page_index: {"records": evidence.get("records", [])}
        for page_index, evidence in layout_prompt.items()
    }
    contract = {
        "records": [
            {
                "source_image_index": 1,
                "company": "",
                "product_or_series": "",
                "formula_no": "",
                "record_date": "",
                "record_bbox": [0.10, 0.18, 0.88, 0.42],
                "materials": [{"name": "", "amount": "", "unit": ""}],
                "process_parameters": [
                    {"name": "", "value": "", "unit": ""}
                ],
                "notes": "",
                "confidence": 0.0,
            }
        ],
        "warnings": [],
    }
    return (
        "每个可见配方输出一条 records 记录；source_image_index 是从 1 开始的图片"
        "序号。formula_no 只填写可见的数字序号，不翻译、不补写“配方”。"
        "每条配方下方的日期行写入该条 record_date。record_bbox 填写该配方完整区域的"
        "归一化坐标 [x1,y1,x2,y2]，仅用于审查定位；无法可靠定位时可省略。材料名称横排及其正下方"
        "对齐的全部数量都写入 materials；只有明确写有“工艺”的行才写入"
        "process_parameters。数字、小数点、加减号、斜杠和范围连接符逐字符保留。"
        "保留原始数量文本、日期、单位、工艺和注意事项。看不清就留空。"
        "知识候选只允许核对客户、产品、材料、工艺名称；新名称必须保留；"
        "amount、date、formula_no、identifier、unit 绝不按历史改写。"
        "只返回符合下列紧凑合同的 JSON 对象：\n"
        f"CONTRACT={json.dumps(contract, ensure_ascii=False)}\n"
        f"OCR={json.dumps(compact_ocr, ensure_ascii=False)}\n"
        f"LAYOUT={json.dumps(compact_layout, ensure_ascii=False)}\n"
        f"KNOWLEDGE={json.dumps(knowledge_prompt, ensure_ascii=False)}"
    )


def _build_knowledge_prompt(
    ocr_pages: list[OCRPage],
    database_path: Path,
) -> dict[str, Any]:
    policy = {
        "role": "reference_only",
        "never_override": [
            "amount",
            "date",
            "formula_no",
            "identifier",
            "unit",
        ],
    }
    if not database_path.exists():
        return {
            "policy": policy,
            "context": {"customer": "", "product": ""},
            "references": [],
        }
    references: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    retrieval = KnowledgeRetrieval(database_path)
    try:
        tokens = [
            (page, token, token.text.strip())
            for page in ocr_pages
            for token in page.tokens[:80]
            if _knowledge_text_candidate(token.text.strip())
        ]
        customer = _infer_prompt_context(tokens, retrieval, "customer")
        product = _infer_prompt_context(
            tokens,
            retrieval,
            "product",
            customer=customer,
        )
        for page, token, raw_text in tokens:
            for term_type in ("customer", "product", "material", "process"):
                if term_type in {"material", "process"} and not customer:
                    continue
                matches = retrieval.retrieve(
                    RetrievalRequest(
                        raw_text=raw_text,
                        term_type=term_type,
                        customer=(
                            customer if term_type != "customer" else ""
                        ),
                        product=(
                            product
                            if term_type in {"material", "process"}
                            else ""
                        ),
                        limit=1,
                    )
                )
                if not matches or matches[0].score < 0.88:
                    continue
                match = matches[0]
                if (
                    term_type in {"product", "material", "process"}
                    and customer
                    and not match.context_aligned
                ):
                    continue
                key = (raw_text, term_type, match.value)
                if key in seen:
                    continue
                seen.add(key)
                references.append(
                    {
                        "raw_text": raw_text,
                        "candidate": match.value,
                        "term_type": term_type,
                        "score": match.score,
                        "reasons": list(match.reasons),
                        "source_image_index": page.image_index,
                        "evidence_token_id": token.id,
                    }
                )
    except Exception as exc:
        logger.warning("知识提示候选不可用（非关键）: %s", exc)
        return {
            "policy": policy,
            "context": {"customer": "", "product": ""},
            "references": [],
        }
    references.sort(
        key=lambda item: (item["score"], item["term_type"]),
        reverse=True,
    )
    return {
        "policy": policy,
        "context": {"customer": customer, "product": product},
        "references": references[:20],
    }


def _infer_prompt_context(
    tokens: list[tuple[OCRPage, OCRToken, str]],
    retrieval: KnowledgeRetrieval,
    term_type: str,
    *,
    customer: str = "",
) -> str:
    ranked = []
    for _page, _token, raw_text in tokens:
        matches = retrieval.retrieve(
            RetrievalRequest(
                raw_text=raw_text,
                term_type=term_type,
                customer=customer,
                limit=1,
            )
        )
        if not matches:
            continue
        match = matches[0]
        if match.score < 0.92 or (customer and not match.context_aligned):
            continue
        ranked.append(match)
    if not ranked:
        return ""
    ranked.sort(key=lambda item: item.score, reverse=True)
    if len(ranked) > 1 and ranked[0].value != ranked[1].value:
        if ranked[0].score - ranked[1].score < 0.08:
            return ""
    return ranked[0].value


def _knowledge_text_candidate(value: str) -> bool:
    if len(value) < 2 or len(value) > 80:
        return False
    compact = value.replace(" ", "")
    if compact.replace(".", "", 1).isdigit():
        return False
    if all(character.isdigit() or character in "-/.年月日" for character in compact):
        return False
    return any(character.isalpha() or "\u4e00" <= character <= "\u9fff" for character in compact)


def _history_candidates(
    structured: dict[str, Any],
    database_path: Path | None = None,
) -> dict[str, list]:
    candidates: dict[str, list] = {}
    database_path = database_path or _knowledge_db_path()
    if not database_path.exists():
        return candidates
    try:
        retrieval = KnowledgeRetrieval(database_path)
        for page in structured.get("pages", []):
            company = page.get("company", {})
            customer = str(
                company.get("standard_value")
                or company.get("raw_value")
                or company.get("value")
                or ""
            ) if isinstance(company, dict) else str(company or "")
            for section in page.get("product_sections", []):
                product, _, _, _ = _extract_field_info(
                    section.get("product_or_series", {})
                )
                for formula in section.get("formulas", []):
                    formula_id = formula.get("formula_id", "formula")
                    for index, material in enumerate(
                        formula.get("materials", []), 1
                    ):
                        material_id = material.get(
                            "material_id", f"material_{index:03d}"
                        )
                        name, _, _, _ = _extract_field_info(
                            material.get("name", {})
                        )
                        _store_retrieval_candidates(
                            candidates,
                            f"{formula_id}__{material_id}__name",
                            retrieval,
                            name,
                            "material",
                            customer,
                            product,
                        )
                    for index, parameter in enumerate(
                        formula.get("process_parameters", []), 1
                    ):
                        parameter_id = parameter.get(
                            "parameter_id", f"parameter_{index:03d}"
                        )
                        name, _, _, _ = _extract_field_info(
                            parameter.get("name", {})
                        )
                        _store_retrieval_candidates(
                            candidates,
                            f"{formula_id}__{parameter_id}__name",
                            retrieval,
                            name,
                            "process",
                            customer,
                            product,
                        )
    except Exception as exc:
        logger.warning("历史匹配不可用（非关键）: %s", exc)
    return candidates


def _store_retrieval_candidates(
    output: dict[str, list],
    field_id: str,
    retrieval: KnowledgeRetrieval,
    raw_value: str,
    term_type: str,
    customer: str,
    product: str,
) -> None:
    if not raw_value:
        return
    matches = retrieval.retrieve(
        RetrievalRequest(
            raw_text=raw_value,
            term_type=term_type,
            customer=customer,
            product=product,
            limit=3,
        )
    )
    if matches:
        output[field_id] = [
            {
                "value": match.value,
                "term_type": match.term_type,
                "score": match.score,
                "context_aligned": match.context_aligned,
                "reasons": list(match.reasons),
            }
            for match in matches
        ]


def _apply_knowledge_correction(
    result: dict[str, Any],
    field_type: str,
    history: list[Any],
) -> dict[str, Any]:
    raw_value = str(result.get("final_value", ""))
    correction_candidates = [
        CorrectionCandidate(
            value=str(match.get("value", match.get("standard_name", ""))),
            score=float(match.get("score", 0.0)),
            context_aligned=bool(match.get("context_aligned", False)),
            reasons=tuple(match.get("reasons", [])),
        )
        for match in history
        if match.get("value") or match.get("standard_name")
    ]
    evidence_present = any(
        candidate.get("evidence")
        for candidate in result.get("candidates", [])
        if candidate.get("source") in {"vlm", "ocr_base"}
    )
    decision = decide_correction(
        field_type=field_type,
        raw_value=raw_value,
        candidates=correction_candidates,
        evidence_present=evidence_present,
    )
    result["knowledge_trace"] = {
        "original_value": decision.original_value,
        "history_candidate": decision.candidate_value,
        "final_value": decision.value,
        "decision": decision.action,
        "score": decision.score,
        "margin": round(decision.margin, 4),
        "reasons": list(decision.reasons),
    }
    for match in history[:3]:
        value = str(match.get("value", match.get("standard_name", "")))
        if value:
            result.setdefault("candidates", []).append(
                {
                    "value": value,
                    "source": "knowledge_history",
                    "confidence": float(match.get("score", 0.0)),
                    "evidence": [],
                    "context_aligned": bool(
                        match.get("context_aligned", False)
                    ),
                    "reasons": list(match.get("reasons", [])),
                }
            )
    if decision.action == "AUTO_CORRECT":
        result["final_value"] = decision.value
        result["final_source"] = "knowledge_assisted"
        result["final_confidence"] = round(
            min(0.98, max(float(result.get("final_confidence", 0.0)), decision.score)),
            4,
        )
    elif decision.action == "SUGGEST":
        result["status"] = "NEED_REVIEW"
    result.setdefault("reasons", []).append(
        f"knowledge:{decision.action}"
    )
    return result


def _extract_records_from_vlm(vlm_result: dict[str, Any]) -> list[dict[str, Any]]:
    pages = vlm_result.get("pages", [])
    if pages:
        records = []
        for page in pages:
            image_index = int(page.get("source_image_index", 1))
            for section in page.get("product_sections", []):
                for formula in section.get("formulas", []):
                    record = dict(formula)
                    record["source_image_indexes"] = [image_index]
                    records.append(record)
        return records
    return list(vlm_result.get("records", []))


def _extract_field_info(
    field_object: Any,
) -> tuple[str, float, list[str], list[float] | None]:
    if not field_object:
        return "", 0.0, [], None
    if isinstance(field_object, str):
        return field_object, 0.8, [], None
    if isinstance(field_object, dict):
        return (
            str(field_object.get("value", field_object.get("raw_value", ""))),
            float(field_object.get("confidence", 0.8)),
            list(field_object.get("evidence_token_ids", [])),
            field_object.get("bbox"),
        )
    return "", 0.0, [], None


def _find_ocr_candidate(
    evidence_token_ids: list[str],
    field_bbox: list[float] | None,
    field_value: str,
    source_image_indexes: list[int],
    ocr_tokens_by_id: dict[str, Any],
    ocr_tokens_by_page: dict[int, list],
    ocr_results: list[OCRPage],
) -> Any | None:
    """Compatibility wrapper for callers that expect one token."""
    image_index = int((source_image_indexes or [1])[0])
    associated = associate_field(
        FieldEvidence(
            field_id="compat",
            field_type="text",
            source_image_index=image_index,
            field_bbox=field_bbox,
            record_bbox=None,
            evidence_token_ids=evidence_token_ids,
            vlm_value=field_value,
        ),
        ocr_results,
        None,
    )
    if not associated:
        return None
    token_id = associated[0].token_ids[0]
    return ocr_tokens_by_id.get(token_id)


def _bbox_iou(a: list[float], b: list[float]) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    if x2 <= x1 or y2 <= y1:
        return 0.0
    intersection = (x2 - x1) * (y2 - y1)
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    union = area_a + area_b - intersection
    return intersection / union if union > 0 else 0.0


def _fused_to_dict(fused: FusedField) -> dict[str, Any]:
    return {
        "field_id": fused.field_id,
        "field_type": fused.field_type,
        "final_value": fused.final_value,
        "final_confidence": fused.final_confidence,
        "final_source": fused.final_source,
        "status": fused.status,
        "reasons": fused.reasons,
        "candidates": [
            {
                "value": candidate.value,
                "source": candidate.source,
                "confidence": candidate.confidence,
                "evidence": candidate.evidence,
            }
            for candidate in fused.raw_candidates
        ],
    }


def _ocr_page_to_dict(page: OCRPage) -> dict[str, Any]:
    return {
        "image_index": page.image_index,
        "width": page.width,
        "height": page.height,
        "provider": page.provider,
        "model": page.model,
        "elapsed_ms": page.elapsed_ms,
        "average_confidence": page.average_confidence,
        "tokens": [
            {
                "id": token.id,
                "text": token.text,
                "confidence": token.confidence,
                "bbox": token.bbox,
                "polygon": token.polygon,
                "center": [token.center_x, token.center_y],
                "line_index": token.line_index,
                "candidate_only": token.candidate_only,
            }
            for token in page.tokens
        ],
        "warnings": page.warnings,
    }


def _reconstruct_ocr_page(data: dict[str, Any]) -> OCRPage:
    tokens = []
    for item in data.get("tokens", []):
        bbox = item.get("bbox", [0, 0, 0, 0])
        center = item.get(
            "center",
            [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2],
        )
        tokens.append(
            OCRToken(
                id=item.get("id", ""),
                text=item.get("text", ""),
                confidence=float(item.get("confidence", 0.0)),
                polygon=item.get("polygon", []),
                bbox=bbox,
                center_x=center[0],
                center_y=center[1],
                line_index=item.get("line_index"),
                candidate_only=bool(item.get("candidate_only", False)),
            )
        )
    return OCRPage(
        image_index=int(data.get("image_index", 1)),
        width=int(data.get("width", 0)),
        height=int(data.get("height", 0)),
        tokens=tokens,
        average_confidence=float(data.get("average_confidence", 0.0)),
        provider=data.get("provider", ""),
        model=data.get("model", ""),
        elapsed_ms=int(data.get("elapsed_ms", 0)),
        warnings=list(data.get("warnings", [])),
    )


def _hash_payload(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _build_ocr_cache_key(
    image_path: Path,
    rotation: str,
    preprocess: dict[str, Any],
    ocr_config: dict[str, Any],
    model_status: dict[str, Any],
) -> str:
    return _hash_payload(
        {
            "image": compute_image_hash(image_path),
            "rotation": rotation,
            "preprocess_version": "dual-image-v2",
            "preprocess": preprocess,
            "provider": ocr_config.get("provider"),
            "tier": ocr_config.get("tier"),
            "det_model": model_status.get("det_model"),
            "rec_model": model_status.get("rec_model"),
            "device": ocr_config.get("device"),
            "minimum_score": ocr_config.get("minimum_score"),
            "orientation": ocr_config.get("use_textline_orientation"),
            "parser": "paddleocr-v6-parser-v2",
        }
    )


async def _recognize_with_cache(
    manager: Any,
    cache: FileRecognitionCache,
    image_path: Path,
    image_index: int,
    cache_enabled: bool,
    cache_key: str,
) -> tuple[OCRPage, bool]:
    cached = cache.get_json("ocr", cache_key) if cache_enabled else None
    if cached:
        manager.ensure_loaded()
        page = _reconstruct_ocr_page(cached)
        cache_hit = True
    else:
        page = await manager.recognize_async(image_path)
        scope_token_ids(page, 1)
        if cache_enabled:
            cache.put_json("ocr", cache_key, _ocr_page_to_dict(page))
        cache_hit = False
    scope_token_ids(page, image_index)
    return page, cache_hit


def _demo_mode() -> bool:
    if _as_bool(os.environ.get("DEMO_MODE", "")):
        return True
    try:
        from .settings import SettingsService

        return bool(
            SettingsService(DATA_ROOT).load().get("demo_mode")
        )
    except Exception:
        return False


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
