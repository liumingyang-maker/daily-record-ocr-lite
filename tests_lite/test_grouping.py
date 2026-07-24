"""分组模块测试：一页多配方/跨页分组/编号重复/公司匹配。"""


from lite_app.grouping.models import (
    BusinessEntities,
    make_formula_id,
    make_page_id,
    make_provisional_id,
)
from lite_app.grouping.service import (
    build_business_entities,
    is_formula_number_token,
    normalize_formula_no,
)
from lite_app.grouping.storage import (
    build_formula_detail,
    build_tree_response,
    load_business_entities,
    save_business_entities,
)


class TestFormulaNumberNormalization:
    def test_circled_numbers(self):
        assert normalize_formula_no("①") == "1"
        assert normalize_formula_no("②") == "2"
        assert normalize_formula_no("⑤") == "5"
        assert normalize_formula_no("⑩") == "10"

    def test_parenthesized_numbers(self):
        assert normalize_formula_no("(1)") == "1"
        assert normalize_formula_no("（3）") == "3"

    def test_dotted_numbers(self):
        assert normalize_formula_no("1.") == "1"
        assert normalize_formula_no("2、") == "2"
        assert normalize_formula_no("3．") == "3"

    def test_formula_prefix(self):
        assert normalize_formula_no("配方1") == "1"
        assert normalize_formula_no("配方 3") == "3"

    def test_plain_number(self):
        assert normalize_formula_no("5") == "5"

    def test_empty(self):
        assert normalize_formula_no("") == ""

    def test_non_number(self):
        assert normalize_formula_no("abc") == ""

    def test_is_formula_number_token(self):
        assert is_formula_number_token("①")
        assert is_formula_number_token("②")
        assert is_formula_number_token("(1)")
        assert is_formula_number_token("配方3")
        assert not is_formula_number_token("PA66")
        assert not is_formula_number_token("工艺")


class TestStableIds:
    def test_page_id(self):
        assert make_page_id(1) == "page_001"
        assert make_page_id(12) == "page_012"

    def test_formula_id(self):
        fid = make_formula_id("job123", "page_001", 2)
        assert fid == "job123__page_001__formula_002"

    def test_formula_id_stability(self):
        """配方 ID 不因公司/产品/编号修改而改变。"""
        fid1 = make_formula_id("job1", "page_001", 1)
        fid2 = make_formula_id("job1", "page_001", 1)
        assert fid1 == fid2

    def test_provisional_id(self):
        pid = make_provisional_id("company", "重庆新材")
        assert pid.startswith("company_provisional_")
        # 相同输入相同 ID
        assert make_provisional_id("company", "重庆新材") == pid

    def test_different_pages_different_formula_ids(self):
        """不同页面的配方 ID 不同。"""
        fid1 = make_formula_id("job1", "page_001", 1)
        fid2 = make_formula_id("job1", "page_002", 1)
        assert fid1 != fid2


class TestBuildBusinessEntities:
    def test_one_page_one_company_multiple_formulas(self):
        """一页一个公司、多条配方。"""
        vlm_result = {
            "pages": [{
                "source_image_index": 1,
                "company": {"raw_value": "A公司", "standard_value": "A公司", "confidence": 0.95},
                "product_sections": [{
                    "product_or_series": {"raw_value": "PA66GF30", "standard_value": "PA66GF30"},
                    "product_type": "material_grade",
                    "formulas": [
                        {"formula_no": "①", "record_date": {"value": "24.7.10"}, "materials": [{"name": {"value": "PA66"}, "amount": {"value": "60"}}], "process_parameters": []},
                        {"formula_no": "②", "record_date": {"value": "24.7.11"}, "materials": [{"name": {"value": "GF30"}, "amount": {"value": "30"}}], "process_parameters": []},
                        {"formula_no": "③", "record_date": {"value": "24.7.12"}, "materials": [], "process_parameters": []},
                    ],
                }],
                "warnings": [],
            }],
        }
        entities = build_business_entities("job1", vlm_result)

        assert len(entities.pages) == 1
        assert len(entities.company_groups) == 1
        assert entities.company_groups[0].display_name == "A公司"
        assert len(entities.product_groups) == 1
        assert len(entities.formulas) == 3
        # 配方编号正确
        assert entities.formulas[0].formula_no_normalized == "1"
        assert entities.formulas[1].formula_no_normalized == "2"
        assert entities.formulas[2].formula_no_normalized == "3"

    def test_same_company_cross_page(self):
        """同公司跨页：合并分组但不合并配方。"""
        vlm_result = {
            "pages": [
                {
                    "source_image_index": 1,
                    "company": {"raw_value": "A公司", "confidence": 0.9},
                    "product_sections": [{
                        "product_or_series": {"raw_value": "产品X"},
                        "formulas": [
                            {"formula_no": "①", "record_date": {"value": "24.7.10"}, "materials": [], "process_parameters": []},
                            {"formula_no": "②", "record_date": {"value": "24.7.11"}, "materials": [], "process_parameters": []},
                        ],
                    }],
                    "warnings": [],
                },
                {
                    "source_image_index": 2,
                    "company": {"raw_value": "A公司", "confidence": 0.9},
                    "product_sections": [{
                        "product_or_series": {"raw_value": "产品X"},
                        "formulas": [
                            {"formula_no": "③", "record_date": {"value": "24.7.12"}, "materials": [], "process_parameters": []},
                            {"formula_no": "④", "record_date": {"value": "24.7.13"}, "materials": [], "process_parameters": []},
                        ],
                    }],
                    "warnings": [],
                },
            ],
        }
        entities = build_business_entities("job1", vlm_result)

        # 1 个公司
        assert len(entities.company_groups) == 1
        assert entities.company_groups[0].display_name == "A公司"
        # 跨 2 页
        assert len(entities.company_groups[0].source_image_indexes) == 2
        # 4 条独立配方
        assert len(entities.formulas) == 4
        # 来源图片分别正确
        assert entities.formulas[0].source_image_index == 1
        assert entities.formulas[1].source_image_index == 1
        assert entities.formulas[2].source_image_index == 2
        assert entities.formulas[3].source_image_index == 2

    def test_duplicate_formula_no_not_merged(self):
        """编号重复但不能合并。"""
        vlm_result = {
            "pages": [
                {
                    "source_image_index": 1,
                    "company": {"raw_value": "A公司"},
                    "product_sections": [{
                        "product_or_series": {"raw_value": "X"},
                        "formulas": [{"formula_no": "①", "record_date": {"value": "24.7.10"}, "materials": [], "process_parameters": []}],
                    }],
                    "warnings": [],
                },
                {
                    "source_image_index": 2,
                    "company": {"raw_value": "A公司"},
                    "product_sections": [{
                        "product_or_series": {"raw_value": "X"},
                        "formulas": [{"formula_no": "①", "record_date": {"value": "24.8.01"}, "materials": [], "process_parameters": []}],
                    }],
                    "warnings": [],
                },
            ],
        }
        entities = build_business_entities("job1", vlm_result)

        # 2 条配方，formula_id 不同
        assert len(entities.formulas) == 2
        assert entities.formulas[0].formula_id != entities.formulas[1].formula_id

    def test_same_company_different_products(self):
        """同公司不同产品。"""
        vlm_result = {
            "pages": [{
                "source_image_index": 1,
                "company": {"raw_value": "B公司"},
                "product_sections": [
                    {
                        "product_or_series": {"raw_value": "产品A"},
                        "formulas": [{"formula_no": "①", "record_date": {"value": ""}, "materials": [], "process_parameters": []}],
                    },
                    {
                        "product_or_series": {"raw_value": "产品B"},
                        "formulas": [{"formula_no": "①", "record_date": {"value": ""}, "materials": [], "process_parameters": []}],
                    },
                ],
                "warnings": [],
            }],
        }
        entities = build_business_entities("job1", vlm_result)

        assert len(entities.company_groups) == 1
        assert len(entities.product_groups) == 2
        assert len(entities.formulas) == 2

    def test_legacy_records_format(self):
        """兼容旧格式 records[]。"""
        vlm_result = {
            "page_heading": "C公司",
            "records": [
                {"source_image_indexes": [1], "record_date": "24.7.10", "title": "配方1", "materials": [{"name": "PA66", "amount": "60", "unit": "kg", "confidence": 0.9}], "process_parameters": [], "notes": "", "confidence": 0.9, "warnings": []},
                {"source_image_indexes": [1], "record_date": "24.7.11", "title": "配方2", "materials": [], "process_parameters": [], "notes": "", "confidence": 0.8, "warnings": []},
            ],
            "warnings": [],
        }
        entities = build_business_entities("job1", vlm_result)

        assert len(entities.formulas) == 2
        assert len(entities.company_groups) == 1
        assert entities.company_groups[0].display_name == "C公司"


class TestBusinessEntityStorage:
    def test_save_and_load(self, tmp_path):
        """保存和加载业务实体。"""
        vlm_result = {
            "pages": [{
                "source_image_index": 1,
                "company": {"raw_value": "测试公司", "confidence": 0.9},
                "product_sections": [{
                    "product_or_series": {"raw_value": "测试产品"},
                    "formulas": [{"formula_no": "①", "record_date": {"value": "24.7.10"}, "materials": [{"name": {"value": "PA66"}, "amount": {"value": "60"}}], "process_parameters": []}],
                }],
                "warnings": [],
            }],
        }
        entities = build_business_entities("job1", vlm_result)
        save_business_entities(tmp_path, entities)

        loaded = load_business_entities(tmp_path)
        assert loaded is not None
        assert len(loaded.formulas) == 1
        assert loaded.formulas[0].formula_no_raw == "①"
        assert len(loaded.company_groups) == 1

    def test_load_nonexistent(self, tmp_path):
        """加载不存在的文件返回 None。"""
        assert load_business_entities(tmp_path) is None

    def test_tree_response(self):
        """构建公司树响应。"""
        vlm_result = {
            "pages": [{
                "source_image_index": 1,
                "company": {"raw_value": "A公司"},
                "product_sections": [{
                    "product_or_series": {"raw_value": "X"},
                    "formulas": [
                        {"formula_no": "①", "record_date": {"value": "24.7.10"}, "materials": [], "process_parameters": []},
                        {"formula_no": "②", "record_date": {"value": "24.7.11"}, "materials": [], "process_parameters": []},
                    ],
                }],
                "warnings": [],
            }],
        }
        entities = build_business_entities("job1", vlm_result)
        tree = build_tree_response(entities)

        assert "summary" in tree
        assert "companies" in tree
        assert tree["summary"]["formula_count"] == 2
        assert len(tree["companies"]) == 1
        assert tree["companies"][0]["display_name"] == "A公司"

    def test_formula_detail(self):
        """构建配方详情。"""
        vlm_result = {
            "pages": [{
                "source_image_index": 1,
                "company": {"raw_value": "A公司"},
                "product_sections": [{
                    "product_or_series": {"raw_value": "X"},
                    "formulas": [{"formula_no": "①", "record_date": {"value": "24.7.10"}, "materials": [{"name": {"value": "PA66"}, "amount": {"value": "60"}, "unit": {"value": "kg"}}], "process_parameters": [{"name": {"value": "转速"}, "value": {"value": "50"}, "unit": {"value": "Hz"}}]}],
                }],
                "warnings": [],
            }],
        }
        entities = build_business_entities("job1", vlm_result)
        fid = entities.formulas[0].formula_id
        detail = build_formula_detail(entities, fid)

        assert detail is not None
        assert detail["formula_no_raw"] == "①"
        assert len(detail["materials"]) == 1
        assert detail["materials"][0]["name"]["raw_value"] == "PA66"
        assert len(detail["process_parameters"]) == 1

    def test_formula_detail_not_found(self):
        """配方不存在返回 None。"""
        entities = BusinessEntities()
        assert build_formula_detail(entities, "nonexistent") is None


class TestSummary:
    def test_summary_counts(self):
        """摘要统计正确。"""
        vlm_result = {
            "pages": [
                {
                    "source_image_index": 1,
                    "company": {"raw_value": "A公司"},
                    "product_sections": [{
                        "product_or_series": {"raw_value": "X"},
                        "formulas": [
                            {"formula_no": "①", "record_date": {"value": ""}, "materials": [{"name": {"value": "PA66", "confidence": 0.9}, "amount": {"value": "60", "confidence": 0.9}}], "process_parameters": []},
                            {"formula_no": "②", "record_date": {"value": ""}, "materials": [], "process_parameters": []},
                        ],
                    }],
                    "warnings": [],
                },
                {
                    "source_image_index": 2,
                    "company": {"raw_value": "B公司"},
                    "product_sections": [{
                        "product_or_series": {"raw_value": "Y"},
                        "formulas": [{"formula_no": "①", "record_date": {"value": ""}, "materials": [{"name": {"value": "GF"}, "amount": {"value": "30"}}], "process_parameters": []}],
                    }],
                    "warnings": [],
                },
            ],
        }
        entities = build_business_entities("job1", vlm_result)
        summary = entities.get_summary()

        assert summary["image_count"] == 2
        assert summary["company_count"] == 2
        assert summary["formula_count"] == 3
