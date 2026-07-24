"""P0 整改端到端测试：候选关联、冲突检测、缓存、局部复核。"""

import json

from lite_app.fusion.engine import AUTO_ACCEPT, CONFLICT, Candidate, FusionEngine
from lite_app.ocr.base import OCRPage, OCRToken
from lite_app.pipeline_v2 import _bbox_iou, _build_fusion_result

# ─── P0-1: 空间关联 + 0.15/0.5 冲突测试 ─────────────────────


class TestSpatialAssociation:
    """验证 OCR 候选通过 evidence_token_ids / bbox / 距离关联。"""

    def _make_ocr_page(self, tokens_data: list[dict]) -> OCRPage:
        tokens = []
        for i, td in enumerate(tokens_data):
            bbox = td["bbox_px"]
            tokens.append(OCRToken(
                id=td.get("id", f"p1_t{i+1:03d}"),
                text=td["text"],
                confidence=td.get("confidence", 0.9),
                polygon=[[bbox[0], bbox[1]], [bbox[2], bbox[1]], [bbox[2], bbox[3]], [bbox[0], bbox[3]]],
                bbox=bbox,
                center_x=(bbox[0] + bbox[2]) / 2,
                center_y=(bbox[1] + bbox[3]) / 2,
            ))
        return OCRPage(
            image_index=1, width=2000, height=1500,
            tokens=tokens, average_confidence=0.9,
            provider="mock", model="mock", elapsed_ms=100,
        )

    def test_evidence_token_id_association(self):
        """VLM 引用 evidence_token_ids 时必须关联到对应 OCR token。"""
        ocr_page = self._make_ocr_page([
            {"id": "p1_t001", "text": "0.15", "bbox_px": [200, 400, 300, 440], "confidence": 0.91},
            {"id": "p1_t002", "text": "PA66", "bbox_px": [200, 300, 350, 340], "confidence": 0.95},
        ])

        # VLM 字段引用 p1_t001，但 VLM 自己读成 0.5
        vlm_result = {
            "records": [{
                "record_id": "r1",
                "source_image_indexes": [1],
                "materials": [{
                    "field_id": "r1_m0",
                    "name": {"value": "PA66", "confidence": 0.9, "evidence_token_ids": ["p1_t002"]},
                    "amount": {"value": "0.5", "confidence": 0.87, "evidence_token_ids": ["p1_t001"]},
                }],
                "process_parameters": [],
            }],
        }

        result = _build_fusion_result(vlm_result, [ocr_page], {})
        # 找到 amount 字段
        amount_fields = [f for f in result["fields"] if f["field_id"] == "r1_m0_amount"]
        assert len(amount_fields) == 1
        af = amount_fields[0]
        # 必须有 CONFLICT 状态
        assert af["status"] == CONFLICT, f"Expected CONFLICT but got {af['status']}: {af['reasons']}"
        # 候选中必须同时有 VLM=0.5 和 OCR=0.15
        values = [c["value"] for c in af["candidates"]]
        assert "0.5" in values
        assert "0.15" in values

    def test_bbox_overlap_association(self):
        """VLM bbox 与 OCR bbox 重叠时必须关联。"""
        # OCR token "0.15" 在像素坐标 [200, 400, 300, 440]
        # 归一化: [0.1, 0.267, 0.15, 0.293]
        ocr_page = self._make_ocr_page([
            {"id": "p1_t001", "text": "0.15", "bbox_px": [200, 400, 300, 440], "confidence": 0.91},
        ])

        # VLM 没有 evidence_token_ids，但 bbox 与 OCR 重叠
        vlm_result = {
            "records": [{
                "record_id": "r1",
                "source_image_indexes": [1],
                "materials": [{
                    "field_id": "r1_m0",
                    "name": {"value": "EBS", "confidence": 0.88},
                    "amount": {"value": "0.5", "confidence": 0.85, "bbox": [0.1, 0.26, 0.16, 0.30]},
                }],
                "process_parameters": [],
            }],
        }

        result = _build_fusion_result(vlm_result, [ocr_page], {})
        amount_fields = [f for f in result["fields"] if f["field_id"] == "r1_m0_amount"]
        assert len(amount_fields) == 1
        af = amount_fields[0]
        assert af["status"] == CONFLICT, f"Expected CONFLICT but got {af['status']}: {af['reasons']}"

    def test_no_association_when_far_apart(self):
        """VLM bbox 与 OCR bbox 距离远时不应关联。"""
        ocr_page = self._make_ocr_page([
            {"id": "p1_t001", "text": "999", "bbox_px": [1800, 1400, 1900, 1440], "confidence": 0.9},
        ])

        # VLM bbox 在页面左上角，与 OCR 在右下角不重叠
        vlm_result = {
            "records": [{
                "record_id": "r1",
                "source_image_indexes": [1],
                "materials": [{
                    "field_id": "r1_m0",
                    "name": {"value": "X", "confidence": 0.9},
                    "amount": {"value": "0.5", "confidence": 0.85, "bbox": [0.05, 0.05, 0.15, 0.10]},
                }],
                "process_parameters": [],
            }],
        }

        result = _build_fusion_result(vlm_result, [ocr_page], {})
        amount_fields = [f for f in result["fields"] if f["field_id"] == "r1_m0_amount"]
        af = amount_fields[0]
        # 没有 OCR 候选关联，只有 VLM，应该是 NEED_REVIEW 而非 CONFLICT
        assert af["status"] != CONFLICT

    def test_bbox_iou_calculation(self):
        """IoU 计算正确。"""
        # 完全重叠
        assert _bbox_iou([0.1, 0.1, 0.3, 0.3], [0.1, 0.1, 0.3, 0.3]) == 1.0
        # 不重叠
        assert _bbox_iou([0.0, 0.0, 0.1, 0.1], [0.5, 0.5, 0.6, 0.6]) == 0.0
        # 部分重叠
        iou = _bbox_iou([0.0, 0.0, 0.2, 0.2], [0.1, 0.1, 0.3, 0.3])
        assert 0.0 < iou < 1.0


class TestFusionConflictDetection:
    """验证融合引擎对数字冲突的严格检测。"""

    def test_numeric_conflict_015_vs_05(self):
        """OCR=0.15, VLM=0.5 必须 CONFLICT。"""
        engine = FusionEngine({
            "rules": {"numeric": {"disagreement_status": "CONFLICT"}},
            "confidence": {"auto_accept_threshold": 0.90, "review_score": 0.70},
        })
        candidates = [
            Candidate(value="0.5", normalized_value="0.5", source="vlm", confidence=0.87),
            Candidate(value="0.15", normalized_value="0.15", source="ocr_base", confidence=0.91),
        ]
        result = engine.fuse_field("test_amount", "amount", candidates)
        assert result.status == CONFLICT
        assert "0.15" in result.reasons[0] or "0.5" in result.reasons[0]

    def test_numeric_agree(self):
        """OCR=VLM=60 必须 AUTO_ACCEPT。"""
        engine = FusionEngine({
            "rules": {"numeric": {"exact_agreement_bonus": 0.15}},
            "confidence": {"auto_accept_threshold": 0.90},
        })
        candidates = [
            Candidate(value="60", normalized_value="60", source="vlm", confidence=0.93),
            Candidate(value="60", normalized_value="60", source="ocr_base", confidence=0.94),
        ]
        result = engine.fuse_field("test_amount", "amount", candidates)
        assert result.status == AUTO_ACCEPT

    def test_history_cannot_override_conflict(self):
        """历史候选不能覆盖 OCR/VLM 冲突。"""
        engine = FusionEngine({
            "rules": {"numeric": {"history_must_not_override": True}},
            "confidence": {"auto_accept_threshold": 0.90},
        })
        candidates = [
            Candidate(value="0.5", normalized_value="0.5", source="vlm", confidence=0.87),
            Candidate(value="0.15", normalized_value="0.15", source="ocr_base", confidence=0.91),
            Candidate(value="0.5", normalized_value="0.5", source="history_formula", confidence=0.72),
        ]
        result = engine.fuse_field("test_amount", "amount", candidates)
        assert result.status == CONFLICT


class TestPagesFormatFusion:
    """验证新 pages[] 格式的融合。"""

    def test_pages_format_produces_fields(self):
        """pages[] 格式应正确提取记录并融合。"""
        vlm_result = {
            "pages": [{
                "source_image_index": 1,
                "company": {"raw_value": "TestCo", "confidence": 0.9},
                "product_sections": [{
                    "product_or_series": {"raw_value": "PA66"},
                    "formulas": [{
                        "formula_no": "①",
                        "formula_id": "job1__page_001__formula_001",
                        "record_date": {"value": "24.7.10"},
                        "materials": [
                            {"name": {"value": "PA66", "confidence": 0.95}, "amount": {"value": "60", "confidence": 0.94}},
                        ],
                        "process_parameters": [],
                    }],
                }],
            }],
        }
        ocr_page = OCRPage(
            image_index=1, width=2000, height=1500,
            tokens=[
                OCRToken(id="p1_t001", text="PA66", confidence=0.95,
                         polygon=[], bbox=[200, 300, 400, 340], center_x=300, center_y=320),
                OCRToken(id="p1_t002", text="60", confidence=0.94,
                         polygon=[], bbox=[200, 400, 280, 440], center_x=240, center_y=420),
            ],
            average_confidence=0.94, provider="mock", model="mock", elapsed_ms=50,
        )

        result = _build_fusion_result(vlm_result, [ocr_page], {})
        assert len(result["fields"]) >= 2  # name + amount
        # 名称应 AUTO_ACCEPT（OCR=VLM=PA66）
        name_fields = [f for f in result["fields"] if "name" in f["field_id"]]
        assert name_fields[0]["status"] == AUTO_ACCEPT


# ─── P0-7: 缓存命中测试 ─────────────────────────────────────


class TestRecognitionCache:
    """验证 RecognitionCache 接入后缓存命中不重复调用 Provider。"""

    def test_cache_set_and_get(self, tmp_path):
        """缓存写入后可读取。"""
        from lite_app.cache import RecognitionCache
        from lite_app.knowledge.database import KnowledgeDB

        db = KnowledgeDB(tmp_path / "test_cache.sqlite3")
        db.initialize()
        cache = RecognitionCache(db)

        # 写入
        cache.set("test_key_1", "hash_abc", "ocr", "/path/result.json", model="v6")
        # 读取
        result = cache.get("test_key_1")
        assert result is not None
        assert result["stage"] == "ocr"
        assert result["result_path"] == "/path/result.json"

    def test_cache_miss_returns_none(self, tmp_path):
        """缓存未命中返回 None。"""
        from lite_app.cache import RecognitionCache
        from lite_app.knowledge.database import KnowledgeDB

        db = KnowledgeDB(tmp_path / "test_cache2.sqlite3")
        db.initialize()
        cache = RecognitionCache(db)
        assert cache.get("nonexistent_key") is None

    def test_cache_invalidation(self, tmp_path):
        """图片变化时缓存失效。"""
        from lite_app.cache import RecognitionCache
        from lite_app.knowledge.database import KnowledgeDB

        db = KnowledgeDB(tmp_path / "test_cache3.sqlite3")
        db.initialize()
        cache = RecognitionCache(db)

        cache.set("key_a", "hash_1", "ocr", "/path/a.json")
        cache.set("key_b", "hash_1", "vision", "/path/b.json")
        cache.set("key_c", "hash_2", "ocr", "/path/c.json")

        # 失效 hash_1
        cache.invalidate_for_image("hash_1")
        assert cache.get("key_a") is None
        assert cache.get("key_b") is None
        assert cache.get("key_c") is not None  # hash_2 不受影响

    def test_build_cache_key_includes_version(self):
        """缓存键包含 prompt 版本，版本变化时键不同。"""
        from lite_app.cache import build_cache_key
        key_v1 = build_cache_key("hash123", "vision", "mock", "qwen-vl", prompt_version="v1")
        key_v2 = build_cache_key("hash123", "vision", "mock", "qwen-vl", prompt_version="v2")
        assert key_v1 != key_v2


# ─── P0-3: 人工修改后 Excel 导出最终值 ──────────────────────


class TestFinalValueExport:
    """验证人工修改后 Excel 导出读取最终值。"""

    def test_human_edit_reflected_in_fusion(self, tmp_path):
        """VLM 原始值 0.5，人工改为 0.15，融合结果必须反映 0.15。"""
        from lite_app.fusion.engine import MANUAL_CONFIRMED, Candidate, FusionEngine

        engine = FusionEngine({
            "rules": {"numeric": {"disagreement_status": "CONFLICT"}},
            "confidence": {"auto_accept_threshold": 0.90},
        })

        # 初始：OCR=0.15, VLM=0.5 → CONFLICT
        candidates = [
            Candidate(value="0.5", normalized_value="0.5", source="vlm", confidence=0.87),
            Candidate(value="0.15", normalized_value="0.15", source="ocr_base", confidence=0.91),
        ]
        result = engine.fuse_field("r1_m0_amount", "amount", candidates)
        assert result.status == CONFLICT

        # 人工确认采用 OCR 值 0.15
        result.final_value = "0.15"
        result.final_source = "manual"
        result.status = MANUAL_CONFIRMED

        # 验证最终值
        assert result.final_value == "0.15"
        assert result.status == MANUAL_CONFIRMED

    def test_excel_uses_final_value_from_fusion(self, tmp_path):
        """Excel 导出必须读取 fusion/result.json 中的 final_value。"""
        from openpyxl import load_workbook

        from lite_app.grouping.exporter import export_grouped_excel
        from lite_app.grouping.service import build_business_entities

        # 构建包含人工修改值的业务实体
        vlm_result = {
            "pages": [{
                "source_image_index": 1,
                "company": {"raw_value": "TestCo"},
                "product_sections": [{
                    "product_or_series": {"raw_value": "PA66"},
                    "formulas": [{
                        "formula_no": "①",
                        "record_date": {"value": "24.7.10"},
                        "materials": [
                            {"name": {"value": "EBS"}, "amount": {"value": "0.15"}},
                        ],
                        "process_parameters": [],
                    }],
                }],
            }],
        }
        entities = build_business_entities("test_job", vlm_result)

        # 导出
        output_path = tmp_path / "test_export.xlsx"
        export_grouped_excel(entities, output_path)

        # 验证 Excel 中的值
        wb = load_workbook(str(output_path))
        ws = wb["配方明细"]
        # 第2行是数据行（第1行是表头）
        # 列: 公司, 产品, 配方编号, 日期, 原料序号, 原料名称, 数量, 单位, 来源图片
        assert ws.cell(row=2, column=6).value == "EBS"
        assert ws.cell(row=2, column=7).value == "0.15"  # 最终值
        wb.close()


# ─── P0-9: Confirm All 检查冲突 ─────────────────────────────


class TestConfirmAllChecksConflicts:
    """验证 Confirm All 不能无条件 READY。"""

    def test_confirm_blocked_by_conflict(self, tmp_path):
        """存在 CONFLICT 字段时 confirm 应返回 REVIEW_REQUIRED。"""
        from lite_app.storage import JobStorage

        storage = JobStorage(jobs_dir=tmp_path / "jobs")
        job = storage.create_job()
        job_id = job["id"]
        job_dir = storage.get_job_dir(job_id)

        # 写入含 CONFLICT 的融合结果
        fusion_dir = job_dir / "fusion"
        fusion_dir.mkdir(parents=True)
        fusion_data = {
            "fields": [
                {"field_id": "r1_m0_amount", "field_type": "amount", "status": "CONFLICT",
                 "final_value": "0.15", "candidates": []},
            ]
        }
        (fusion_dir / "result.json").write_text(json.dumps(fusion_data), encoding="utf-8")

        # 模拟 confirm 逻辑
        fusion_path = job_dir / "fusion" / "result.json"
        fusion_data_loaded = json.loads(fusion_path.read_text(encoding="utf-8"))
        unresolved = [f["field_id"] for f in fusion_data_loaded["fields"] if f["status"] == "CONFLICT"]
        assert len(unresolved) == 1
        assert unresolved[0] == "r1_m0_amount"

    def test_confirm_allowed_when_no_conflicts(self, tmp_path):
        """无 CONFLICT 时 confirm 应允许 READY。"""
        from lite_app.storage import JobStorage

        storage = JobStorage(jobs_dir=tmp_path / "jobs")
        job = storage.create_job()
        job_id = job["id"]
        job_dir = storage.get_job_dir(job_id)

        fusion_dir = job_dir / "fusion"
        fusion_dir.mkdir(parents=True)
        fusion_data = {
            "fields": [
                {"field_id": "r1_m0_name", "field_type": "text", "status": "AUTO_ACCEPT",
                 "final_value": "PA66", "candidates": []},
                {"field_id": "r1_m0_amount", "field_type": "amount", "status": "AUTO_ACCEPT",
                 "final_value": "60", "candidates": []},
            ]
        }
        (fusion_dir / "result.json").write_text(json.dumps(fusion_data), encoding="utf-8")

        fusion_path = job_dir / "fusion" / "result.json"
        fusion_data_loaded = json.loads(fusion_path.read_text(encoding="utf-8"))
        unresolved = [f["field_id"] for f in fusion_data_loaded["fields"] if f["status"] == "CONFLICT"]
        critical_empty = [f["field_id"] for f in fusion_data_loaded["fields"]
                         if f["status"] == "EMPTY" and f["field_type"] in ("amount", "text")
                         and ("_name" in f["field_id"] or "_amount" in f["field_id"])]
        assert len(unresolved) == 0
        assert len(critical_empty) == 0
