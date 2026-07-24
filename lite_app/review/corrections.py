"""修正日志服务：记录每次字段值变化。"""

from __future__ import annotations

import logging
from typing import Any

from ..knowledge.database import KnowledgeDB

logger = logging.getLogger(__name__)


class CorrectionService:
    """修正日志管理。"""

    def __init__(self, db: KnowledgeDB) -> None:
        self.db = db

    def record_correction(
        self,
        job_id: str,
        field_id: str,
        field_type: str,
        old_value: str,
        new_value: str,
        chosen_source: str = "manual",
        ocr_value: str = "",
        vlm_value: str = "",
        record_id: str = "",
    ) -> None:
        """记录一次字段修正。"""
        self.db.add_correction(
            job_id=job_id,
            field_id=field_id,
            field_type=field_type,
            old_value=old_value,
            new_value=new_value,
            chosen_source=chosen_source,
            ocr_value=ocr_value,
            vlm_value=vlm_value,
            record_id=record_id,
        )
        logger.info(
            "修正记录: job=%s field=%s '%s' -> '%s' (source=%s)",
            job_id, field_id, old_value, new_value, chosen_source,
        )

    def get_job_corrections(self, job_id: str) -> list[dict[str, Any]]:
        """获取任务的所有修正记录。"""
        return self.db.get_corrections_for_job(job_id)
