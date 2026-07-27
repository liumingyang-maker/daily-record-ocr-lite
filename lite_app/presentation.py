"""User-facing presentation helpers for recognition jobs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

_STATUS: dict[str, tuple[str, str, str]] = {
    "UPLOADED": ("正在识别", "查看进度", "recognizing"),
    "PREPARING": ("正在识别", "查看进度", "recognizing"),
    "PREPROCESSING": ("正在识别", "查看进度", "recognizing"),
    "RECOGNIZING": ("正在识别", "查看进度", "recognizing"),
    "OCR_RUNNING": ("正在识别", "查看进度", "recognizing"),
    "VISION_RUNNING": ("正在识别", "查看进度", "recognizing"),
    "MATCHING_HISTORY": ("正在整理配方", "查看进度", "recognizing"),
    "FUSING": ("正在整理配方", "查看进度", "recognizing"),
    "REVIEW_REQUIRED": ("需要确认", "继续确认", "need_review"),
    "READY": ("可以导出", "导出 Excel", "ready"),
    "EXPORTING": ("正在生成 Excel", "查看进度", "recognizing"),
    "EXPORTED": ("已完成", "查看记录", "exported"),
    "FAILED": ("识别失败", "查看原因并重试", "failed"),
    "FAILED_SCHEMA": ("识别失败", "查看原因并重试", "failed"),
    "DEGRADED": ("识别失败", "查看原因并重试", "failed"),
}

_PROGRESS_STEP = {
    "UPLOADED": 1,
    "PREPARING": 1,
    "PREPROCESSING": 1,
    "RECOGNIZING": 2,
    "OCR_RUNNING": 2,
    "VISION_RUNNING": 2,
    "MATCHING_HISTORY": 3,
    "FUSING": 3,
    "REVIEW_REQUIRED": 4,
    "READY": 4,
    "EXPORTING": 4,
    "EXPORTED": 4,
}


def user_status(status: str) -> dict[str, str]:
    """Translate an internal status into a stable user-facing action."""
    label, next_action, tone = _STATUS.get(
        str(status), ("正在整理", "查看详情", "recognizing")
    )
    return {"label": label, "next_action": next_action, "tone": tone}


def present_job(job: dict[str, Any]) -> dict[str, Any]:
    """Build the recognition-record row without exposing engine internals."""
    status = str(job.get("status", ""))
    status_view = user_status(status)
    business = job.get("business_summary")
    if not isinstance(business, dict):
        business = {}

    customers = _clean_values(business.get("customers"))
    products = _clean_values(business.get("products"))
    date_min = str(business.get("date_min", "")).strip()
    date_max = str(business.get("date_max", "")).strip()

    return {
        "id": str(job.get("id", "")),
        "customer": "、".join(customers) if customers else "正在整理",
        "product": "、".join(products) if products else "正在整理",
        "date_range": _date_range(date_min, date_max),
        "image_count": len(job.get("images", [])),
        "created_at": str(job.get("created_at", ""))[:19],
        "status": status_view,
        "next_action": status_view["next_action"],
        "progress_step": _PROGRESS_STEP.get(status, 1),
        "advanced": {
            "job_id": str(job.get("id", "")),
            "provider": str(job.get("provider", "")),
            "model": str(job.get("model", "")),
        },
    }


def present_stored_job(job: dict[str, Any], job_dir: Path) -> dict[str, Any]:
    """Derive business labels from the canonical projection without changing job.json."""
    if isinstance(job.get("business_summary"), dict):
        return present_job(job)

    from .grouping.storage import load_business_entities

    entities = load_business_entities(job_dir)
    if entities is None:
        return present_job(job)

    dates = sorted(
        {
            formula.record_date.standard_value.strip()
            or formula.record_date.raw_value.strip()
            for formula in entities.formulas
            if formula.record_date.standard_value.strip()
            or formula.record_date.raw_value.strip()
        }
    )
    derived = dict(job)
    derived["business_summary"] = {
        "customers": [group.display_name for group in entities.company_groups],
        "products": [group.display_name for group in entities.product_groups],
        "date_min": dates[0] if dates else "",
        "date_max": dates[-1] if dates else "",
    }
    return present_job(derived)


def present_error(
    category: str | None,
    *,
    http_status: int | None,
    request_id: str | None,
) -> dict[str, Any]:
    """Translate connection failures into one message and one next action."""
    normalized = str(category or "").upper()
    if http_status in {401, 403} or any(
        marker in normalized for marker in ("AUTH", "UNAUTHORIZED", "FORBIDDEN")
    ):
        message = "AI 识别服务未通过身份验证"
        next_action = "检查 API Key 和服务权限后重新测试"
    elif "TIMEOUT" in normalized:
        message = "AI 识别服务响应超时"
        next_action = "检查网络连接和服务状态后重新测试"
    elif any(marker in normalized for marker in ("JSON", "SCHEMA", "FORMAT")):
        message = "AI 返回的结果格式无法识别"
        next_action = "确认模型支持 JSON 输出后重新测试"
    elif any(marker in normalized for marker in ("TRANSPORT", "CONNECTION", "PROVIDER")):
        message = "无法连接 AI 识别服务"
        next_action = "检查服务地址和网络连接后重新测试"
    else:
        message = "测试未通过"
        next_action = "打开诊断信息检查状态后重新测试"
    return {
        "message": message,
        "next_action": next_action,
        "advanced": {
            "error_category": normalized or None,
            "http_status": http_status,
            "request_id": request_id,
        },
    }


def _clean_values(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _date_range(date_min: str, date_max: str) -> str:
    if not date_min and not date_max:
        return "待确认"
    if not date_min:
        return date_max
    if not date_max or date_min == date_max:
        return date_min
    return f"{date_min} 至 {date_max}"
