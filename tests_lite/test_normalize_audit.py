"""Regression tests for normalization audit trail and gate separation."""

from __future__ import annotations

from lite_app.contracts import normalize_legacy_result


class TestNormalizeParameterName:
    """test_normalize_parameter_name: parameter_name → name normalization."""

    def test_parameter_name_renamed_to_name(self):
        result = {
            "pages": [{
                "source_image_index": 1,
                "product_sections": [{
                    "formulas": [{
                        "process_parameters": [{
                            "parameter_name": {"value": "温度", "confidence": 0.9, "evidence_token_ids": [], "bbox": None},
                            "parameter_value": {"value": "180", "confidence": 0.8, "evidence_token_ids": [], "bbox": None},
                        }]
                    }]
                }]
            }]
        }
        normalized = normalize_legacy_result(result, "test")
        param = normalized["pages"][0]["product_sections"][0]["formulas"][0]["process_parameters"][0]
        assert "name" in param
        assert param["name"]["value"] == "温度"
        assert "parameter_name" not in param
        # Check audit warning
        assert "normalized_parameter_name" in param["warnings"]

    def test_parameter_value_renamed_to_value(self):
        result = {
            "pages": [{
                "source_image_index": 1,
                "product_sections": [{
                    "formulas": [{
                        "process_parameters": [{
                            "parameter_name": {"value": "压力", "confidence": 0.9, "evidence_token_ids": [], "bbox": None},
                            "parameter_value": {"value": "5", "confidence": 0.8, "evidence_token_ids": [], "bbox": None},
                        }]
                    }]
                }]
            }]
        }
        normalized = normalize_legacy_result(result, "test")
        param = normalized["pages"][0]["product_sections"][0]["formulas"][0]["process_parameters"][0]
        assert "value" in param
        assert param["value"]["value"] == "5"
        assert "parameter_value" not in param
        # Check audit warning
        assert "normalized_parameter_value" in param["warnings"]


class TestNormalizeNotesContent:
    """test_normalize_notes_content: notes.content → value normalization."""

    def test_notes_content_renamed_to_value(self):
        result = {
            "pages": [{
                "source_image_index": 1,
                "product_sections": [{
                    "formulas": [{
                        "notes": {"content": "备注内容", "confidence": 0.9, "evidence_token_ids": [], "bbox": None},
                    }]
                }]
            }]
        }
        normalized = normalize_legacy_result(result, "test")
        notes = normalized["pages"][0]["product_sections"][0]["formulas"][0]["notes"]
        assert "value" in notes
        assert notes["value"] == "备注内容"
        assert "content" not in notes
        # Check audit warning
        formula_warnings = normalized["pages"][0]["product_sections"][0]["formulas"][0]["warnings"]
        assert "normalized_notes_content" in formula_warnings


class TestWarningObjectToString:
    """test_warning_object_to_string: warning objects → strings normalization."""

    def test_warning_object_converted_to_string(self):
        result = {
            "pages": [{
                "source_image_index": 1,
                "warnings": [
                    {"message": "警告信息", "severity": "high"},
                    "普通警告",
                ],
                "product_sections": [{
                    "formulas": [{}]
                }]
            }],
            "warnings": [],
        }
        normalized = normalize_legacy_result(result, "test")
        page_warnings = normalized["pages"][0]["warnings"]
        assert all(isinstance(w, str) for w in page_warnings)
        assert "警告信息" in page_warnings
        assert "普通警告" in page_warnings
        # Check audit warning
        assert "normalized_warning_object" in page_warnings


class TestBboxPixelToNull:
    """test_bbox_pixel_to_null: pixel coordinates bbox → null normalization."""

    def test_pixel_bbox_normalized_to_null(self):
        result = {
            "pages": [{
                "source_image_index": 1,
                "warnings": [],
                "company": {
                    "raw_value": "公司",
                    "confidence": 0.9,
                    "evidence_token_ids": [],
                    "bbox": [100, 200, 300, 400],  # pixel coordinates
                },
                "product_sections": [{
                    "formulas": [{}]
                }]
            }]
        }
        normalized = normalize_legacy_result(result, "test")
        company = normalized["pages"][0]["company"]
        assert company["bbox"] is None
        # Check audit warning at page level
        page_warnings = normalized["pages"][0]["warnings"]
        assert "normalized_invalid_bbox" in page_warnings

    def test_normalized_bbox_preserved(self):
        result = {
            "pages": [{
                "source_image_index": 1,
                "company": {
                    "raw_value": "公司",
                    "confidence": 0.9,
                    "evidence_token_ids": [],
                    "bbox": [0.1, 0.2, 0.3, 0.4],  # normalized coordinates
                },
                "product_sections": [{
                    "formulas": [{}]
                }]
            }]
        }
        normalized = normalize_legacy_result(result, "test")
        company = normalized["pages"][0]["company"]
        assert company["bbox"] == [0.1, 0.2, 0.3, 0.4]


class TestMissingSchemaVersionWarning:
    """test_missing_schema_version_warning: missing schema_version adds warning."""

    def test_missing_schema_version_adds_warning(self):
        result = {
            "pages": [{
                "source_image_index": 1,
                "product_sections": [{
                    "formulas": [{}]
                }]
            }]
        }
        normalized = normalize_legacy_result(result, "test")
        assert normalized["schema_version"] == "record-v1"
        assert "normalized_missing_schema_version" in normalized["warnings"]

    def test_existing_schema_version_no_warning(self):
        result = {
            "schema_version": "record-v1",
            "pages": [{
                "source_image_index": 1,
                "product_sections": [{
                    "formulas": [{}]
                }]
            }],
            "warnings": [],
        }
        normalized = normalize_legacy_result(result, "test")
        assert "normalized_missing_schema_version" not in normalized["warnings"]


class TestRecognitionGate:
    """test_recognition_gate: recognition gate logic."""

    def test_recognition_gate_all_conditions_met(self):
        """Test recognition gate passes when all conditions are met."""
        import tempfile
        from pathlib import Path

        from scripts.pipeline_gate import check_gate

        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir)
            # Create required files
            (job_dir / "vision").mkdir()
            (job_dir / "vision" / "raw_response.txt").write_text('{"test": true}')
            (job_dir / "vision" / "structured_result.json").write_text('{}')
            (job_dir / "review").mkdir()
            (job_dir / "review" / "final_result.json").write_text('{}')
            (job_dir / "fusion").mkdir()
            (job_dir / "fusion" / "result.json").write_text('{}')

            job = {
                "id": "test",
                "status": "REVIEW_REQUIRED",
                "validation_errors": [],
                "timings_ms": {"ocr_ms": 100, "vision_ms": 200},
            }
            gate = check_gate(job_dir, job)
            assert gate["recognition_gate_passed"] is True

    def test_recognition_gate_fails_on_schema_error(self):
        """Test recognition gate fails when schema has errors."""
        import tempfile
        from pathlib import Path

        from scripts.pipeline_gate import check_gate

        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir)
            (job_dir / "vision").mkdir()
            (job_dir / "vision" / "raw_response.txt").write_text('{"test": true}')
            (job_dir / "vision" / "structured_result.json").write_text('{}')

            job = {
                "id": "test",
                "status": "FAILED_SCHEMA",
                "validation_errors": [{"error": "test"}],
                "timings_ms": {},
            }
            gate = check_gate(job_dir, job)
            assert gate["recognition_gate_passed"] is False


class TestExportGateReady:
    """test_export_gate_ready: export gate passes when READY with Excel."""

    def test_export_gate_passes_when_ready_with_excel(self):
        import tempfile
        from pathlib import Path

        from scripts.pipeline_gate import check_gate

        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir)
            (job_dir / "vision").mkdir()
            (job_dir / "vision" / "raw_response.txt").write_text('{"test": true}')
            (job_dir / "vision" / "structured_result.json").write_text('{}')
            (job_dir / "review").mkdir()
            (job_dir / "review" / "final_result.json").write_text('{}')
            (job_dir / "fusion").mkdir()
            (job_dir / "fusion" / "result.json").write_text('{}')
            (job_dir / "export").mkdir()
            (job_dir / "export" / "test.xlsx").write_text('')

            job = {
                "id": "test",
                "status": "READY",
                "validation_errors": [],
                "export_file": "export/test.xlsx",
                "timings_ms": {"ocr_ms": 100, "vision_ms": 200},
            }
            gate = check_gate(job_dir, job)
            assert gate["recognition_gate_passed"] is True
            assert gate["export_gate_passed"] is True


class TestExportGateReviewRequired:
    """test_export_gate_review_required: export gate fails when REVIEW_REQUIRED."""

    def test_export_gate_fails_when_review_required(self):
        import tempfile
        from pathlib import Path

        from scripts.pipeline_gate import check_gate

        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir)
            (job_dir / "vision").mkdir()
            (job_dir / "vision" / "raw_response.txt").write_text('{"test": true}')
            (job_dir / "vision" / "structured_result.json").write_text('{}')
            (job_dir / "review").mkdir()
            (job_dir / "review" / "final_result.json").write_text('{}')
            (job_dir / "fusion").mkdir()
            (job_dir / "fusion" / "result.json").write_text('{}')

            job = {
                "id": "test",
                "status": "REVIEW_REQUIRED",
                "validation_errors": [],
                "timings_ms": {"ocr_ms": 100, "vision_ms": 200},
            }
            gate = check_gate(job_dir, job)
            assert gate["recognition_gate_passed"] is True
            assert gate["export_gate_passed"] is False


class TestStableIds:
    """test_stable_ids: stable ID assignment."""

    def test_stable_ids_assigned(self):
        result = {
            "pages": [{
                "source_image_index": 1,
                "product_sections": [{
                    "formulas": [{
                        "materials": [{"name": {"value": "PA66"}}],
                        "process_parameters": [{"name": {"value": "温度"}}],
                    }]
                }]
            }]
        }
        normalized = normalize_legacy_result(result, "test-job")
        formula = normalized["pages"][0]["product_sections"][0]["formulas"][0]
        assert formula["formula_id"] == "test-job__page_001__formula_001"
        assert formula["materials"][0]["material_id"] == "material_001"
        assert formula["process_parameters"][0]["parameter_id"] == "parameter_001"

    def test_stable_ids_deterministic(self):
        result = {
            "pages": [{
                "source_image_index": 1,
                "product_sections": [{
                    "formulas": [{
                        "materials": [{"name": {"value": "PA66"}}],
                    }]
                }]
            }]
        }
        n1 = normalize_legacy_result(result, "job-1")
        n2 = normalize_legacy_result(result, "job-1")
        assert n1["pages"][0]["product_sections"][0]["formulas"][0]["formula_id"] == \
               n2["pages"][0]["product_sections"][0]["formulas"][0]["formula_id"]


class TestCallTypeDetection:
    """test_call_type_detection: call type detection logic."""

    def test_real_api_detection(self):
        import tempfile
        from pathlib import Path

        from scripts.pipeline_gate import check_gate

        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir)
            (job_dir / "vision").mkdir()
            (job_dir / "vision" / "raw_response.txt").write_text('{"test": true}')
            (job_dir / "vision" / "structured_result.json").write_text('{}')

            job = {
                "id": "test",
                "status": "REVIEW_REQUIRED",
                "validation_errors": [],
                "timings_ms": {"ocr_ms": 100, "vision_ms": 120000},  # 120 seconds
                "vision_engine": {"cache_hit": False},
            }
            gate = check_gate(job_dir, job)
            assert gate["call_type"] == "real_api"

    def test_cache_replay_detection(self):
        import tempfile
        from pathlib import Path

        from scripts.pipeline_gate import check_gate

        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir)
            (job_dir / "vision").mkdir()
            (job_dir / "vision" / "raw_response.txt").write_text('{"test": true}')
            (job_dir / "vision" / "structured_result.json").write_text('{}')

            job = {
                "id": "test",
                "status": "REVIEW_REQUIRED",
                "validation_errors": [],
                "timings_ms": {"ocr_ms": 100, "vision_ms": 5},  # 5ms = cache
                "vision_engine": {"cache_hit": True},
            }
            gate = check_gate(job_dir, job)
            assert gate["call_type"] == "cache_replay"
