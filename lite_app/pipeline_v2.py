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

        t0 = time.time()
        for i, ocr_file in enumerate(ocr_files, 1):
            ocr_path = job_dir / ocr_file
            page_result = await ocr_manager.recognize_async(ocr_path)
            page_result.image_index = i
            ocr_results.append(page_result)

            # 保存 OCR 结果
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
            (ocr_dir / f"page_{i:02d}_base.json").write_text(
                json.dumps(ocr_json, ensure_ascii=False, indent=2), encoding="utf-8"
            )

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

        # 调用 VLM
        t0 = time.time()
        image_paths = [job_dir / f for f in vlm_files]
        raw_response = await vision_provider.analyze(
            image_paths, system_prompt, user_prompt, schema
        )
        timings["vision_ms"] = int((time.time() - t0) * 1000)

        # 保存 VLM 原始响应
        vision_dir = job_dir / "vision"
        vision_dir.mkdir(exist_ok=True)
        (vision_dir / "raw_response.txt").write_text(raw_response, encoding="utf-8")

        # 解析 JSON
        vlm_result = extract_json(raw_response)
        (vision_dir / "structured_result.json").write_text(
            json.dumps(vlm_result, ensure_ascii=False, indent=2), encoding="utf-8"
        )

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
        storage.save_job(job)
        logger.info("任务 %s 双引擎识别完成: %s", job_id, job["status"])
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
    """构建融合结果（简化版：基于 VLM 结果 + OCR 交叉验证）。"""
    from .config import load_export_config, PROJECT_ROOT
    import yaml

    # 加载融合规则
    rules_path = PROJECT_ROOT / "config" / "fusion_rules.yaml"
    rules = {}
    if rules_path.exists():
        with open(rules_path, encoding="utf-8") as f:
            rules = yaml.safe_load(f) or {}

    engine = FusionEngine(rules)
    fields: list[dict[str, Any]] = []

    # 构建 OCR token 查找表
    ocr_tokens_by_text: dict[str, list] = {}
    for page in ocr_results:
        for token in page.tokens:
            ocr_tokens_by_text.setdefault(token.text, []).append(token)

    for record in vlm_result.get("records", []):
        record_id = record.get("record_id", "r1")

        for mat in record.get("materials", []):
            field_id = mat.get("field_id", f"{record_id}_m")
            name_obj = mat.get("name", {})
            amount_obj = mat.get("amount", {})

            # 名称字段
            name_val = name_obj.get("value", "") if isinstance(name_obj, dict) else str(name_obj)
            name_conf = name_obj.get("confidence", 0.8) if isinstance(name_obj, dict) else 0.8

            candidates = []
            if name_val:
                candidates.append(Candidate(
                    value=name_val,
                    normalized_value=normalize_text(name_val),
                    source="vlm",
                    confidence=name_conf,
                    evidence=name_obj.get("evidence_token_ids", []) if isinstance(name_obj, dict) else [],
                ))
                # OCR 交叉验证
                if name_val in ocr_tokens_by_text:
                    ocr_tok = ocr_tokens_by_text[name_val][0]
                    candidates.append(Candidate(
                        value=ocr_tok.text,
                        normalized_value=normalize_text(ocr_tok.text),
                        source="ocr_base",
                        confidence=ocr_tok.confidence,
                        evidence=[ocr_tok.id],
                    ))
                # 历史候选
                if field_id in history_candidates:
                    for hc in history_candidates[field_id][:2]:
                        candidates.append(Candidate(
                            value=hc["standard_name"],
                            normalized_value=normalize_text(hc["standard_name"]),
                            source="history_material",
                            confidence=hc["score"] * 0.7,
                            evidence=[f"history:{hc['match_type']}"],
                        ))

            fused_name = engine.fuse_field(f"{field_id}_name", "text", candidates)
            fields.append(_fused_to_dict(fused_name))

            # 数量字段
            amount_val = amount_obj.get("value", "") if isinstance(amount_obj, dict) else str(amount_obj)
            amount_conf = amount_obj.get("confidence", 0.8) if isinstance(amount_obj, dict) else 0.8

            amount_candidates = []
            if amount_val:
                amount_candidates.append(Candidate(
                    value=amount_val,
                    normalized_value=amount_val,
                    source="vlm",
                    confidence=amount_conf,
                    evidence=amount_obj.get("evidence_token_ids", []) if isinstance(amount_obj, dict) else [],
                ))
                if amount_val in ocr_tokens_by_text:
                    ocr_tok = ocr_tokens_by_text[amount_val][0]
                    amount_candidates.append(Candidate(
                        value=ocr_tok.text,
                        normalized_value=ocr_tok.text,
                        source="ocr_base",
                        confidence=ocr_tok.confidence,
                        evidence=[ocr_tok.id],
                    ))

            fused_amount = engine.fuse_field(f"{field_id}_amount", "amount", amount_candidates)
            fields.append(_fused_to_dict(fused_amount))

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
