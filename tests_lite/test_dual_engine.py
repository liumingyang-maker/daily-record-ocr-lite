"""OCR Provider 和融合引擎测试。"""

import pytest
from PIL import Image

from lite_app.fusion.engine import (
    AUTO_ACCEPT,
    CONFLICT,
    EMPTY,
    NEED_REVIEW,
    Candidate,
    FusionEngine,
)
from lite_app.knowledge.database import KnowledgeDB
from lite_app.knowledge.matcher import HistoryMatcher, normalize_text
from lite_app.layout.geometry import TextLine, cluster_lines, pair_materials_amounts
from lite_app.ocr.base import OCRPage, OCRToken
from lite_app.ocr.manager import OCRModelManager
from lite_app.ocr.mock import MockOCRProvider

# ─── OCR Mock Provider ──────────────────────────────────────


class TestMockOCRProvider:
    def test_recognize_returns_tokens(self, tmp_path):
        img = Image.new("RGB", (200, 100), color=(255, 255, 255))
        img_path = tmp_path / "test.jpg"
        img.save(img_path, format="JPEG")

        provider = MockOCRProvider()
        page = provider.recognize(img_path)

        assert isinstance(page, OCRPage)
        assert page.width == 200
        assert page.height == 100
        assert len(page.tokens) > 0
        assert page.provider == "mock"
        assert page.average_confidence > 0

    def test_token_structure(self, tmp_path):
        img = Image.new("RGB", (200, 100))
        img_path = tmp_path / "test.jpg"
        img.save(img_path, format="JPEG")

        provider = MockOCRProvider()
        page = provider.recognize(img_path)
        token = page.tokens[0]

        assert isinstance(token, OCRToken)
        assert token.id
        assert token.text
        assert 0 <= token.confidence <= 1
        assert len(token.bbox) == 4
        assert token.center_x > 0
        assert token.center_y > 0

    def test_custom_mock_data(self, tmp_path):
        img = Image.new("RGB", (400, 300))
        img_path = tmp_path / "test.jpg"
        img.save(img_path, format="JPEG")

        custom_data = [
            {"text": "PA66", "confidence": 0.95, "bbox": [0.1, 0.2, 0.3, 0.25]},
            {"text": "60", "confidence": 0.93, "bbox": [0.1, 0.3, 0.2, 0.35]},
        ]
        provider = MockOCRProvider(mock_data=custom_data)
        page = provider.recognize(img_path)

        assert len(page.tokens) == 2
        assert page.tokens[0].text == "PA66"
        assert page.tokens[1].text == "60"

    def test_evidence_json(self, tmp_path):
        img = Image.new("RGB", (200, 100))
        img_path = tmp_path / "test.jpg"
        img.save(img_path, format="JPEG")

        provider = MockOCRProvider()
        page = provider.recognize(img_path)
        evidence = page.to_evidence_json()

        assert "image_index" in evidence
        assert "image_size" in evidence
        assert "ocr_tokens" in evidence
        # 坐标应归一化到 0~1
        for tok in evidence["ocr_tokens"]:
            assert 0 <= tok["center"][0] <= 1
            assert 0 <= tok["center"][1] <= 1

    def test_model_singleton(self):
        OCRModelManager.reset()
        mgr1 = OCRModelManager()
        mgr2 = OCRModelManager()
        assert mgr1 is mgr2
        OCRModelManager.reset()


# ─── 融合引擎 ───────────────────────────────────────────────


class TestFusionEngine:
    @pytest.fixture
    def engine(self):
        rules = {
            "rules": {
                "text": {"ocr_vlm_exact_agreement_bonus": 0.12, "low_ocr_penalty": 0.15, "low_ocr_threshold": 0.60},
                "numeric": {"disagreement_status": "CONFLICT", "exact_agreement_bonus": 0.15, "history_must_not_override": True},
                "model_code": {"digit_difference_status": "CONFLICT", "letter_case_only_can_normalize": True},
            },
            "confidence": {"auto_accept_threshold": 0.90, "review_score": 0.70},
        }
        return FusionEngine(rules)

    def test_ocr_vlm_agree_text(self, engine):
        candidates = [
            Candidate(value="PA66", normalized_value="pa66", source="ocr_base", confidence=0.94, evidence=["t1"]),
            Candidate(value="PA66", normalized_value="pa66", source="vlm", confidence=0.93, evidence=["t1"]),
        ]
        result = engine.fuse_field("r1_m1_name", "text", candidates)
        assert result.status == AUTO_ACCEPT
        assert result.final_value == "PA66"
        assert result.final_source == "ocr_vlm_agree"
        assert result.final_confidence > 0.90

    def test_ocr_vlm_disagree_text(self, engine):
        candidates = [
            Candidate(value="PA66", normalized_value="pa66", source="ocr_base", confidence=0.80),
            Candidate(value="PA68", normalized_value="pa68", source="vlm", confidence=0.85),
        ]
        result = engine.fuse_field("r1_m1_name", "text", candidates)
        assert result.status in (NEED_REVIEW, CONFLICT)

    def test_numeric_agree(self, engine):
        candidates = [
            Candidate(value="60", normalized_value="60", source="ocr_base", confidence=0.94),
            Candidate(value="60", normalized_value="60", source="vlm", confidence=0.93),
        ]
        result = engine.fuse_field("r1_m1_amount", "amount", candidates)
        assert result.status == AUTO_ACCEPT
        assert result.final_value == "60"
        assert result.final_confidence > 0.90

    def test_numeric_conflict(self, engine):
        """数字冲突必须标记为 CONFLICT。"""
        candidates = [
            Candidate(value="0.15", normalized_value="0.15", source="ocr_base", confidence=0.91),
            Candidate(value="0.5", normalized_value="0.5", source="vlm", confidence=0.87),
        ]
        result = engine.fuse_field("r1_m3_amount", "amount", candidates)
        assert result.status == CONFLICT
        assert "冲突" in result.reasons[0] or "OCR" in result.reasons[0]

    def test_numeric_conflict_history_cannot_override(self, engine):
        """即使历史支持 VLM，数字冲突也不能自动通过。"""
        candidates = [
            Candidate(value="0.15", normalized_value="0.15", source="ocr_base", confidence=0.91),
            Candidate(value="0.5", normalized_value="0.5", source="vlm", confidence=0.87),
            Candidate(value="0.5", normalized_value="0.5", source="history_formula", confidence=0.72),
        ]
        result = engine.fuse_field("r1_m3_amount", "amount", candidates)
        assert result.status == CONFLICT

    def test_empty_candidates(self, engine):
        result = engine.fuse_field("r1_m1_unit", "text", [])
        assert result.status == EMPTY
        assert result.final_value == ""

    def test_ocr_only(self, engine):
        candidates = [
            Candidate(value="EBS", normalized_value="ebs", source="ocr_base", confidence=0.88),
        ]
        result = engine.fuse_field("r1_m2_name", "text", candidates)
        assert result.final_value == "EBS"
        assert result.final_source == "ocr_base"

    def test_model_code_case_insensitive(self, engine):
        candidates = [
            Candidate(value="pa66", normalized_value="pa66", source="ocr_base", confidence=0.92),
            Candidate(value="PA66", normalized_value="pa66", source="vlm", confidence=0.90),
        ]
        result = engine.fuse_field("r1_m1_name", "model_code", candidates)
        assert result.status == AUTO_ACCEPT

    def test_model_code_digit_conflict(self, engine):
        candidates = [
            Candidate(value="PA66", normalized_value="pa66", source="ocr_base", confidence=0.92),
            Candidate(value="PA68", normalized_value="pa68", source="vlm", confidence=0.90),
        ]
        result = engine.fuse_field("r1_m1_name", "model_code", candidates)
        assert result.status == CONFLICT


# ─── 知识库和匹配 ───────────────────────────────────────────


class TestKnowledgeDB:
    @pytest.fixture
    def db(self, tmp_path):
        db = KnowledgeDB(tmp_path / "test.sqlite3")
        db.initialize()
        yield db
        db.close()

    def test_add_and_find_material(self, db):
        db.add_material("PA66", category="尼龙", default_unit="kg")
        result = db.find_material_by_name("PA66")
        assert result is not None
        assert result["standard_name"] == "PA66"

    def test_alias_match(self, db):
        mid = db.add_material("EBS")
        db.add_alias(mid, "E8S", alias_type="ocr_error")
        result = db.find_material_by_name("E8S")
        assert result is not None
        assert result["standard_name"] == "EBS"

    def test_correction_log(self, db):
        db.add_correction("job1", "r1_m1_amount", "amount", "0.5", "0.15", "manual", "0.5", "0.15")
        corrections = db.get_corrections_for_job("job1")
        assert len(corrections) == 1
        assert corrections[0]["old_value"] == "0.5"
        assert corrections[0]["new_value"] == "0.15"

    def test_cache(self, db):
        db.set_cache("key1", "hash1", "ocr", "/path/result.json", model="v6")
        result = db.get_cache("key1")
        assert result is not None
        assert result["stage"] == "ocr"

        db.invalidate_cache("hash1")
        assert db.get_cache("key1") is None


class TestHistoryMatcher:
    @pytest.fixture
    def matcher(self, tmp_path):
        db = KnowledgeDB(tmp_path / "test.sqlite3")
        db.initialize()
        db.add_material("PA66", category="尼龙")
        db.add_material("GF30", category="玻纤")
        db.add_material("抗氧剂1010")
        mid = db.add_material("EBS")
        db.add_alias(mid, "E8S", alias_type="ocr_error")
        return HistoryMatcher(db)

    def test_exact_match(self, matcher):
        results = matcher.match_material("PA66")
        assert len(results) > 0
        assert results[0]["standard_name"] == "PA66"
        assert results[0]["match_type"] == "exact"

    def test_ocr_error_alias(self, matcher):
        results = matcher.match_material("E8S")
        assert len(results) > 0
        assert results[0]["standard_name"] == "EBS"

    def test_normalize_text(self):
        assert normalize_text("ＰＡ６６") == "pa66"
        assert normalize_text("  PA66  ") == "pa66"
        assert normalize_text("（测试）") == "(测试)"


# ─── 布局算法 ───────────────────────────────────────────────


class TestLayoutGeometry:
    def _make_token(self, text, cx, cy, w=40, h=20):
        bbox = [cx - w/2, cy - h/2, cx + w/2, cy + h/2]
        return OCRToken(
            id=f"t_{text}",
            text=text,
            confidence=0.9,
            polygon=[[bbox[0], bbox[1]], [bbox[2], bbox[1]], [bbox[2], bbox[3]], [bbox[0], bbox[3]]],
            bbox=bbox,
            center_x=cx,
            center_y=cy,
        )

    def test_cluster_lines(self):
        tokens = [
            self._make_token("PA66", 100, 50),
            self._make_token("GF30", 200, 50),
            self._make_token("60", 100, 80),
            self._make_token("30", 200, 80),
        ]
        lines = cluster_lines(tokens, page_height=200)
        assert len(lines) == 2
        assert len(lines[0].tokens) == 2  # PA66, GF30
        assert len(lines[1].tokens) == 2  # 60, 30

    def test_pair_materials_amounts(self):
        name_line = TextLine(index=0, tokens=[
            self._make_token("PA66", 100, 50),
            self._make_token("GF30", 200, 50),
        ])
        amount_line = TextLine(index=1, tokens=[
            self._make_token("60", 100, 80),
            self._make_token("30", 200, 80),
        ])
        name_line.compute()
        amount_line.compute()

        pairs = pair_materials_amounts(name_line, amount_line)
        assert len(pairs) == 2
        assert pairs[0].name_token.text == "PA66"
        assert pairs[0].amount_token.text == "60"
        assert pairs[1].name_token.text == "GF30"
        assert pairs[1].amount_token.text == "30"

    def test_one_to_one_matching(self):
        """同一数量不能分配给两个原料。"""
        name_line = TextLine(index=0, tokens=[
            self._make_token("A", 100, 50),
            self._make_token("B", 120, 50),  # 非常接近
        ])
        amount_line = TextLine(index=1, tokens=[
            self._make_token("60", 100, 80),
        ])
        name_line.compute()
        amount_line.compute()

        pairs = pair_materials_amounts(name_line, amount_line)
        # 只有一个数量，只能分配给一个原料
        assigned = [p for p in pairs if p.amount_token is not None]
        assert len(assigned) == 1
