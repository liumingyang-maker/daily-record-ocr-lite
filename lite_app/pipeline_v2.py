"""双引擎识别 Pipeline：OCR + VLM + 融合。"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from .config import get_config, load_schema_config
from .fusion.engine import Candidate, FusionEngine, FusedField
from .image_utils_v2 import ImageProcessError, prepare_dual_images
from .knowledge.database import KnowledgeDB
from .knowledge.matcher import HistoryMatcher, normalize_text
from .ocr.base import OCRPage
from .ocr.manager import OCRModelManager
from .storage import JobStorage
from .vision.base import VisionProviderError
from .vision.mock import MockVisionProvider
from .vision.openai_compatible import OpenAICompatibleVisionProvider

logger = logging.getLogger(__name__)


class PipelineError(Exception):
    """Pipeline 处理错误。"""
    pass


def build_vision_provider(vision_config: dict[str, Any]):
    """构建视觉模型 Provider。"""
    provider_name = vision_config.get("provider", "mock")
    if provider_name == "mock":
        from .config import PROJECT_ROOT
        mock_path_str = vision_config.get("mock_result", "config/mock_result.json")
        mock_path = Path(mock_path_str)
        if not mock_path.is_absolute():
            mock_path = PROJECT_ROOT / mock_path
        return MockVisionProvider(mock_path)
    if provider_name == "openai_compatible":
        return OpenAICompatibleVisionProvider(vision_config)
    raise PipelineError(f"未知的 Vision Provider: {provider_name}")


def extract_json(text: str) -> dict[str, Any]:
    """从模型响应中提取 JSON 对象。"""
    text = text.strip()
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
        if isinstance(result, list):
            raise PipelineError("模型返回了 JSON 数组，但需要的是 JSON 对象。")
    except json.JSONDecodeError:
        pass

    # Markdown fence
    import re
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if fence_match:
        try:
            result = json.loads(fence_match.group(1).strip())
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    # 遍历所有 { 位置
    decoder = json.JSONDecoder()
    for i, char in enumerate(text):
        if char != "{":
            continue
        try:
            result, _ = decoder.raw_decode(text, i)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            continue

    raise PipelineError(f"无法从模型响应中解析出 JSON 对象。响应前200字符: {text[:200]}")


async def analyze_job_v2(job_id: str, storage: JobStorage | None = None) -> dict[str, Any]:
    """
    双引擎识别流程：
    预处理 → OCR → VLM(带OCR证据) → 历史匹配 → 融合 → 状态更新
    """
    if storage is None:
        storage = JobStorage()

    cfg = get_config()
    job = storage.get_job(job_id)
    job_dir = storage.get_job_dir(job_id)
    timings: dict[str, int] = {}

    try:
        # 清空旧错误
        job["error"] = ""
        job["validation_errors"] = []
        job["status"] = "PREPROCESSING"
        job["status_message"] = "正在处理图片..."
        storage.save_job(job)

        # ─── 阶段1：预处理（双图）───────────────────────────
        t0 = time.time()
        rotation = job.get("rotation", "auto")
        preprocess_cfg = cfg.preprocess
        vlm_files: list[str] = []
        ocr_files: list[str] = []

        for i, img_info in enumerate(job["images"], 1):
            source_path = job_dir / img_info["source"]
            vlm_name = f"prepared_vlm_{i:02d}.jpg"
            ocr_name = f"prepared_ocr_{i:02d}.jpg"

            info = prepare_dual_images(
                source_path,
                job_dir / vlm_name,
                job_dir / ocr_name,
                rotation=rotation,
                config=preprocess_cfg,
            )
            img_info["prepared_vlm"] = vlm_name
            img_info["prepared_ocr"] = ocr_name
            img_info["prepared"] = vlm_name  # 兼容旧字段
            img_info["width"] = info["vlm_width"]
            img_info["height"] = info["vlm_height"]
            vlm_files.append(vlm_name)
            ocr_files.append(ocr_name)

        timings["preprocess_ms"] = int((time.time() - t0) * 1000)
        storage.save_job(job)

        # ─── 阶段2：OCR ─────────────────────────────────────
        job["status"] = "OCR_RUNNING"
        job["status_message"] = "正在执行 OCR 识别..."
        storage.save_job(job)

        ocr_manager = OCRModelManager()
        ocr_results: list[OCRPage] = []
        ocr_dir = job_dir / "ocr"
        ocr_dir.mkdir(exist_ok=True)

        # 初始化缓存
        from .cache import RecognitionCache, compute_image_hash, build_cache_key
        from .config import PROJECT_ROOT as _PROJ_ROOT
        _cache_db = KnowledgeDB(_PROJ_ROOT / "data" / "knowledge.sqlite3")
        _cache_db.initialize()
        rec_cache = RecognitionCache(_cache_db)
        cache_enabled = cfg.get("cache", {}).get("enabled", True) if isinstance(cfg.get("cache"), dict) else True
        cache_hits = {"ocr": 0, "vision": 0}

        t0 = time.time()
        for i, ocr_file in enumerate(ocr_files, 1):
            ocr_path = job_dir / ocr_file
            ocr_json_path = ocr_dir / f"page_{i:02d}_base.json"

            # 检查 OCR 缓存
            cached_page = None
            if cache_enabled:
                img_hash = compute_image_hash(ocr_path)
                cache_key = build_cache_key(img_hash, "ocr", "paddleocr_v6", ocr_manager.provider_name)
                cached = rec_cache.get(cache_key)
                if cached and ocr_json_path.exists():
                    try:
                        ocr_data = json.loads(ocr_json_path.read_text(encoding="utf-8"))
                        cached_page = _reconstruct_ocr_page(ocr_data)
                        cache_hits["ocr"] += 1
                        logger.info("OCR 缓存命中: page %d", i)
                    except Exception:
                        cached_page = None

            if cached_page:
                page_result = cached_page
            else:
                page_result = await ocr_manager.recognize_async(ocr_path)
                page_result.image_index = i

                # 保存 OCR 结果并写入缓存
                ocr_json = {
                    "image_index": page_result.image_index,
                    "width": page_result.width,
                    "height": page_result.height,
                    "provider": page_result.provider,
                    "model": page_result.model,
                    "elapsed_ms": page_result.elapsed_ms,
                    "average_confidence": page_result.average_confidence,
                    "tokens": [
                        {
                            "id": t.id,
                            "text": t.text,
                            "confidence": t.confidence,
                            "bbox": t.bbox,
                            "center": [t.center_x, t.center_y],
                        }
                        for t in page_result.tokens
                    ],
                    "warnings": page_result.warnings,
                }
                ocr_json_path.write_text(
                    json.dumps(ocr_json, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                if cache_enabled:
                    rec_cache.set(cache_key, img_hash, "ocr", str(ocr_json_path), model=ocr_manager.provider_name)

            ocr_results.append(page_result)

            # 生成 overlay 图
            try:
                from .ocr.overlay import generate_overlay
                overlay_path = ocr_dir / f"page_{i:02d}_overlay.jpg"
                generate_overlay(ocr_path, page_result, overlay_path)
            except Exception as e:
                logger.warning("Overlay 生成失败 (page %d): %s", i, e)

        timings["ocr_ms"] = int((time.time() - t0) * 1000)

        # ─── 阶段3：VLM（带 OCR 证据）──────────────────────
        job["status"] = "VISION_RUNNING"
        job["status_message"] = "正在调用视觉模型..."
        storage.save_job(job)

        vision_cfg = cfg.vision
        vision_provider = build_vision_provider(vision_cfg)
        job["provider"] = vision_cfg.get("provider", "mock")
        job["model"] = vision_cfg.get("model", "")

        # 构建 OCR 证据
        ocr_evidence = [page.to_evidence_json() for page in ocr_results]

        # 构建提示词
        schema_config = load_schema_config()
        system_prompt = schema_config.get("system_prompt", "")
        instructions = schema_config.get("instructions", "")
        schema = schema_config.get("schema", {})

        # 在 user_prompt 中附加 OCR 证据
        ocr_evidence_text = json.dumps(ocr_evidence, ensure_ascii=False, indent=1)
        user_prompt = f"""{instructions}

以下是 PP-OCRv6 识别出的文字证据（含坐标和置信度），请结合原图参考：

{ocr_evidence_text}

请严格按照 JSON Schema 返回结果。只返回 JSON，不要使用 Markdown 代码块。"""

        # 调用 VLM（带缓存检查）
        t0 = time.time()
        image_paths = [job_dir / f for f in vlm_files]
        vision_dir = job_dir / "vision"
        vision_dir.mkdir(exist_ok=True)
        raw_response_path = vision_dir / "raw_response.txt"

        # VLM 缓存：基于所有图片哈希 + prompt版本 + 模型
        vlm_cached = False
        if cache_enabled:
            import hashlib
            combined_hash = hashlib.sha256()
            for ip in image_paths:
                combined_hash.update(compute_image_hash(ip).encode())
            prompt_version = schema_config.get("prompt_version", "unknown")
            vlm_cache_key = build_cache_key(
                combined_hash.hexdigest()[:16], "vision",
                vision_cfg.get("provider", ""), vision_cfg.get("model", ""),
                prompt_version=prompt_version,
            )
            cached_vlm = rec_cache.get(vlm_cache_key)
            if cached_vlm and raw_response_path.exists():
                raw_response = raw_response_path.read_text(encoding="utf-8")
                vlm_cached = True
                cache_hits["vision"] += 1
                logger.info("VLM 缓存命中")

        if not vlm_cached:
            raw_response = await vision_provider.analyze(
                image_paths, system_prompt, user_prompt, schema
            )
            # 保存 VLM 原始响应并写入缓存
            raw_response_path.write_text(raw_response, encoding="utf-8")
            if cache_enabled:
                rec_cache.set(vlm_cache_key, combined_hash.hexdigest(), "vision",
                              str(raw_response_path), model=vision_cfg.get("model", ""),
                              version=prompt_version)

        timings["vision_ms"] = int((time.time() - t0) * 1000)

        # 保存 VLM 原始响应（确保存在）
        if not raw_response_path.exists():
            raw_response_path.write_text(raw_response, encoding="utf-8")

        # 解析 JSON
        vlm_result = extract_json(raw_response)
        (vision_dir / "structured_result.json").write_text(
            json.dumps(vlm_result, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # ─── 阶段3.5：Schema 校验（Draft202012Validator）──────
        from jsonschema import Draft202012Validator
        schema_obj = schema_config.get("schema", {})
        if schema_obj:
            validator = Draft202012Validator(schema_obj)
            validation_errors = []
            for error in validator.iter_errors(vlm_result):
                path = ".".join(str(p) for p in error.absolute_path)
                validation_errors.append(f"{path}: {error.message}" if path else error.message)
            job["validation_errors"] = validation_errors
            if validation_errors:
                logger.warning("任务 %s VLM 结果 Schema 校验有 %d 个问题", job_id, len(validation_errors))

        # ─── 阶段4：历史匹配 ────────────────────────────────
        job["status"] = "MATCHING_HISTORY"
        job["status_message"] = "正在匹配历史知识..."
        storage.save_job(job)

        t0 = time.time()
        history_candidates: dict[str, list] = {}
        try:
            from .config import PROJECT_ROOT
            db_path = PROJECT_ROOT / "data" / "knowledge.sqlite3"
            kb = KnowledgeDB(db_path)
            kb.initialize()
            matcher = HistoryMatcher(kb)

            # 对 VLM 结果中的物料名进行历史匹配
            for record in vlm_result.get("records", []):
                for mat in record.get("materials", []):
                    name_val = mat.get("name", {})
                    name_text = name_val.get("value", "") if isinstance(name_val, dict) else str(name_val)
                    if name_text:
                        matches = matcher.match_material(name_text, max_candidates=3)
                        if matches:
                            field_id = mat.get("field_id", f"{record.get('record_id', 'r')}_{name_text}")
                            history_candidates[field_id] = matches
            timings["history_ms"] = int((time.time() - t0) * 1000)
        except Exception as e:
            logger.warning("历史匹配跳过: %s", e)
            timings["history_ms"] = 0

        # ─── 阶段5：融合 ────────────────────────────────────
        job["status"] = "FUSING"
        job["status_message"] = "正在融合多来源候选..."
        storage.save_job(job)

        t0 = time.time()
        fusion_result = _build_fusion_result(vlm_result, ocr_results, history_candidates)
        timings["fusion_ms"] = int((time.time() - t0) * 1000)

        # 保存融合结果
        fusion_dir = job_dir / "fusion"
        fusion_dir.mkdir(exist_ok=True)
        (fusion_dir / "result.json").write_text(
            json.dumps(fusion_result, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 同时保存为 result.json（兼容旧接口）
        storage.save_result(job_id, vlm_result)

        # ─── 阶段6：构建业务分组 ─────────────────────────────
        try:
            from .grouping.service import build_business_entities
            from .grouping.storage import save_business_entities
            entities = build_business_entities(job_id, vlm_result)
            save_business_entities(job_dir, entities)
            logger.info("任务 %s 业务分组构建完成: %d 公司, %d 配方",
                        job_id, len(entities.company_groups), len(entities.formulas))
        except Exception as e:
            logger.warning("任务 %s 业务分组构建失败（不影响主流程）: %s", job_id, e)

        # 判断是否有冲突
        conflicts = [f for f in fusion_result.get("fields", []) if f.get("status") == "CONFLICT"]
        need_review = [f for f in fusion_result.get("fields", []) if f.get("status") == "NEED_REVIEW"]

        if conflicts:
            job["status"] = "REVIEW_REQUIRED"
            job["status_message"] = f"识别完成，有 {len(conflicts)} 个冲突字段需要确认。"
        elif need_review:
            job["status"] = "REVIEW_REQUIRED"
            job["status_message"] = f"识别完成，有 {len(need_review)} 个字段建议复核。"
        else:
            job["status"] = "READY"
            job["status_message"] = "识别完成，所有字段自动通过。"

        job["timings_ms"] = timings
        job["cache_hits"] = cache_hits
        storage.save_job(job)
        logger.info("任务 %s 双引擎识别完成: %s (cache_hits=%s)", job_id, job["status"], cache_hits)
        return job

    except (ImageProcessError, VisionProviderError, PipelineError) as e:
        job["status"] = "FAILED"
        job["error"] = str(e)
        job["status_message"] = str(e)
        job["timings_ms"] = timings
        storage.save_job(job)
        logger.error("任务 %s 失败: %s", job_id, e)
        raise

    except Exception as e:
        job["status"] = "FAILED"
        job["error"] = f"未知错误: {e}"
        job["status_message"] = f"未知错误: {e}"
        job["timings_ms"] = timings
        storage.save_job(job)
        logger.exception("任务 %s 未知错误", job_id)
        raise PipelineError(f"识别过程出错: {e}")


def _build_fusion_result(
    vlm_result: dict[str, Any],
    ocr_results: list[OCRPage],
    history_candidates: dict[str, list],
) -> dict[str, Any]:
    """构建融合结果：通过 evidence_token_ids、bbox 重叠和空间距离关联 OCR 候选。"""
    from .config import PROJECT_ROOT
    import yaml

    # 加载融合规则
    rules_path = PROJECT_ROOT / "config" / "fusion_rules.yaml"
    rules = {}
    if rules_path.exists():
        with open(rules_path, encoding="utf-8") as f:
            rules = yaml.safe_load(f) or {}

    engine = FusionEngine(rules)
    fields: list[dict[str, Any]] = []

    # 构建 OCR token 索引：by id 和 by page
    ocr_tokens_by_id: dict[str, Any] = {}
    ocr_tokens_by_page: dict[int, list] = {}
    for page in ocr_results:
        page_tokens = []
        for token in page.tokens:
            ocr_tokens_by_id[token.id] = token
            page_tokens.append(token)
        ocr_tokens_by_page[page.image_index] = page_tokens

    # 获取记录列表（兼容 pages[] 和 records[] 格式）
    records = _extract_records_from_vlm(vlm_result)

    for record in records:
        record_id = record.get("record_id", record.get("formula_id", "r1"))
        source_indexes = record.get("source_image_indexes", [1])
        record_bbox = record.get("record_bbox") or record.get("bbox")

        for mat_idx, mat in enumerate(record.get("materials", [])):
            field_id = mat.get("field_id", f"{record_id}_m{mat_idx}")
            name_obj = mat.get("name", {})
            amount_obj = mat.get("amount", {})

            # ─── 名称字段融合 ───
            name_val, name_conf, name_evidence, name_bbox = _extract_field_info(name_obj)
            name_candidates = []
            if name_val:
                name_candidates.append(Candidate(
                    value=name_val,
                    normalized_value=normalize_text(name_val),
                    source="vlm",
                    confidence=name_conf,
                    evidence=name_evidence,
                ))
                # 通过空间关联找 OCR 候选
                ocr_match = _find_ocr_candidate(
                    name_evidence, name_bbox, name_val,
                    source_indexes, ocr_tokens_by_id, ocr_tokens_by_page,
                    ocr_results,
                )
                if ocr_match:
                    name_candidates.append(Candidate(
                        value=ocr_match.text,
                        normalized_value=normalize_text(ocr_match.text),
                        source="ocr_base",
                        confidence=ocr_match.confidence,
                        evidence=[ocr_match.id],
                    ))
                # 历史候选
                if field_id in history_candidates:
                    for hc in history_candidates[field_id][:2]:
                        name_candidates.append(Candidate(
                            value=hc["standard_name"],
                            normalized_value=normalize_text(hc["standard_name"]),
                            source="history_material",
                            confidence=hc["score"] * 0.7,
                            evidence=[f"history:{hc['match_type']}"],
                        ))

            fused_name = engine.fuse_field(f"{field_id}_name", "text", name_candidates)
            fields.append(_fused_to_dict(fused_name))

            # ─── 数量字段融合 ───
            amount_val, amount_conf, amount_evidence, amount_bbox = _extract_field_info(amount_obj)
            amount_candidates = []
            if amount_val:
                amount_candidates.append(Candidate(
                    value=amount_val,
                    normalized_value=amount_val,
                    source="vlm",
                    confidence=amount_conf,
                    evidence=amount_evidence,
                ))
                # 通过空间关联找 OCR 候选
                ocr_match = _find_ocr_candidate(
                    amount_evidence, amount_bbox, amount_val,
                    source_indexes, ocr_tokens_by_id, ocr_tokens_by_page,
                    ocr_results,
                )
                if ocr_match:
                    amount_candidates.append(Candidate(
                        value=ocr_match.text,
                        normalized_value=ocr_match.text,
                        source="ocr_base",
                        confidence=ocr_match.confidence,
                        evidence=[ocr_match.id],
                    ))

            fused_amount = engine.fuse_field(f"{field_id}_amount", "amount", amount_candidates)
            fields.append(_fused_to_dict(fused_amount))

        # ─── 工艺参数字段融合 ───
        for pp_idx, pp in enumerate(record.get("process_parameters", [])):
            pp_field_id = f"{record_id}_pp{pp_idx}"
            pp_name_obj = pp.get("name", {})
            pp_value_obj = pp.get("value", {})

            pp_name_val, pp_name_conf, pp_name_ev, pp_name_bbox = _extract_field_info(pp_name_obj)
            pp_val_val, pp_val_conf, pp_val_ev, pp_val_bbox = _extract_field_info(pp_value_obj)

            # 工艺名称
            pp_name_candidates = []
            if pp_name_val:
                pp_name_candidates.append(Candidate(
                    value=pp_name_val, normalized_value=normalize_text(pp_name_val),
                    source="vlm", confidence=pp_name_conf, evidence=pp_name_ev,
                ))
                ocr_m = _find_ocr_candidate(
                    pp_name_ev, pp_name_bbox, pp_name_val,
                    source_indexes, ocr_tokens_by_id, ocr_tokens_by_page, ocr_results,
                )
                if ocr_m:
                    pp_name_candidates.append(Candidate(
                        value=ocr_m.text, normalized_value=normalize_text(ocr_m.text),
                        source="ocr_base", confidence=ocr_m.confidence, evidence=[ocr_m.id],
                    ))
            fused_pp_name = engine.fuse_field(f"{pp_field_id}_name", "text", pp_name_candidates)
            fields.append(_fused_to_dict(fused_pp_name))

            # 工艺数值
            pp_val_candidates = []
            if pp_val_val:
                pp_val_candidates.append(Candidate(
                    value=pp_val_val, normalized_value=pp_val_val,
                    source="vlm", confidence=pp_val_conf, evidence=pp_val_ev,
                ))
                ocr_m = _find_ocr_candidate(
                    pp_val_ev, pp_val_bbox, pp_val_val,
                    source_indexes, ocr_tokens_by_id, ocr_tokens_by_page, ocr_results,
                )
                if ocr_m:
                    pp_val_candidates.append(Candidate(
                        value=ocr_m.text, normalized_value=ocr_m.text,
                        source="ocr_base", confidence=ocr_m.confidence, evidence=[ocr_m.id],
                    ))
            fused_pp_val = engine.fuse_field(f"{pp_field_id}_value", "amount", pp_val_candidates)
            fields.append(_fused_to_dict(fused_pp_val))

    # 统计
    total = len(fields)
    auto_accept = sum(1 for f in fields if f["status"] == "AUTO_ACCEPT")
    conflict = sum(1 for f in fields if f["status"] == "CONFLICT")
    need_review = sum(1 for f in fields if f["status"] == "NEED_REVIEW")

    return {
        "page_heading": vlm_result.get("page_heading", ""),
        "records": vlm_result.get("records", []),
        "warnings": vlm_result.get("warnings", []),
        "fields": fields,
        "summary": {
            "total_fields": total,
            "auto_accept": auto_accept,
            "conflict": conflict,
            "need_review": need_review,
        },
    }


def _extract_records_from_vlm(vlm_result: dict[str, Any]) -> list[dict[str, Any]]:
    """从 VLM 结果提取记录列表（兼容 pages[] 和 records[] 格式）。"""
    # 新格式 pages[]
    pages = vlm_result.get("pages", [])
    if pages:
        records = []
        for page in pages:
            img_idx = page.get("source_image_index", 1)
            for section in page.get("product_sections", []):
                for formula in section.get("formulas", []):
                    record = dict(formula)
                    record["source_image_indexes"] = [img_idx]
                    record.setdefault("record_id", formula.get("formula_id", "r"))
                    records.append(record)
        return records
    # 旧格式 records[]
    return vlm_result.get("records", [])


def _extract_field_info(field_obj: Any) -> tuple[str, float, list[str], list[float] | None]:
    """从字段对象提取 (value, confidence, evidence_token_ids, bbox)。"""
    if not field_obj:
        return ("", 0.0, [], None)
    if isinstance(field_obj, str):
        return (field_obj, 0.8, [], None)
    if isinstance(field_obj, dict):
        return (
            field_obj.get("value", ""),
            field_obj.get("confidence", 0.8),
            field_obj.get("evidence_token_ids", []),
            field_obj.get("bbox"),
        )
    return ("", 0.0, [], None)


def _find_ocr_candidate(
    evidence_token_ids: list[str],
    field_bbox: list[float] | None,
    field_value: str,
    source_image_indexes: list[int],
    ocr_tokens_by_id: dict[str, Any],
    ocr_tokens_by_page: dict[int, list],
    ocr_results: list[OCRPage],
) -> Any | None:
    """
    通过三种策略关联 OCR 候选：
    1. evidence_token_ids 直接引用
    2. bbox 重叠（归一化坐标）
    3. 文本精确匹配（最后回退）
    """
    # 策略1：VLM 直接引用了 OCR token id
    for tid in evidence_token_ids:
        if tid in ocr_tokens_by_id:
            return ocr_tokens_by_id[tid]

    # 策略2：bbox 重叠匹配
    if field_bbox and len(field_bbox) == 4:
        best_token = None
        best_iou = 0.0
        for img_idx in source_image_indexes:
            page = next((p for p in ocr_results if p.image_index == img_idx), None)
            if not page:
                continue
            page_w, page_h = page.width, page.height
            if page_w == 0 or page_h == 0:
                continue
            for token in page.tokens:
                # 将 OCR 像素 bbox 转为归一化坐标
                ocr_norm_bbox = [
                    token.bbox[0] / page_w,
                    token.bbox[1] / page_h,
                    token.bbox[2] / page_w,
                    token.bbox[3] / page_h,
                ]
                iou = _bbox_iou(field_bbox, ocr_norm_bbox)
                if iou > best_iou:
                    best_iou = iou
                    best_token = token
            # 如果 IoU 太低，尝试中心距离
            if best_iou < 0.1:
                field_cx = (field_bbox[0] + field_bbox[2]) / 2
                field_cy = (field_bbox[1] + field_bbox[3]) / 2
                best_dist = float("inf")
                for token in page.tokens:
                    tcx = token.center_x / page_w
                    tcy = token.center_y / page_h
                    dist = ((field_cx - tcx) ** 2 + (field_cy - tcy) ** 2) ** 0.5
                    if dist < best_dist and dist < 0.05:  # 5% 页面尺寸内
                        best_dist = dist
                        best_token = token
        if best_token and best_iou > 0.05:
            return best_token

    # 策略3：文本精确匹配（最后回退）
    for img_idx in source_image_indexes:
        page = next((p for p in ocr_results if p.image_index == img_idx), None)
        if not page:
            continue
        for token in page.tokens:
            if token.text == field_value:
                return token

    return None


def _bbox_iou(a: list[float], b: list[float]) -> float:
    """计算两个归一化 bbox 的 IoU。"""
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


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
                "value": c.value,
                "source": c.source,
                "confidence": c.confidence,
                "evidence": c.evidence,
            }
            for c in fused.raw_candidates
        ],
    }


def _reconstruct_ocr_page(ocr_data: dict[str, Any]) -> OCRPage:
    """从保存的 JSON 数据重建 OCRPage 对象（缓存命中时使用）。"""
    from .ocr.base import OCRToken
    tokens = []
    for td in ocr_data.get("tokens", []):
        bbox = td.get("bbox", [0, 0, 0, 0])
        center = td.get("center", [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2])
        tokens.append(OCRToken(
            id=td.get("id", ""),
            text=td.get("text", ""),
            confidence=td.get("confidence", 0.0),
            polygon=[[bbox[0], bbox[1]], [bbox[2], bbox[1]], [bbox[2], bbox[3]], [bbox[0], bbox[3]]],
            bbox=bbox,
            center_x=center[0],
            center_y=center[1],
        ))
    return OCRPage(
        image_index=ocr_data.get("image_index", 1),
        width=ocr_data.get("width", 0),
        height=ocr_data.get("height", 0),
        tokens=tokens,
        average_confidence=ocr_data.get("average_confidence", 0.0),
        provider=ocr_data.get("provider", ""),
        model=ocr_data.get("model", ""),
        elapsed_ms=ocr_data.get("elapsed_ms", 0),
        warnings=ocr_data.get("warnings", []),
    )
