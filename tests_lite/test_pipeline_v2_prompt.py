import json

from lite_app import pipeline_v2
from lite_app.config import load_schema_config


def test_business_prompt_contains_complete_record_v1_contract() -> None:
    builder = getattr(pipeline_v2, "build_vision_user_prompt", None)
    assert builder is not None, "pipeline_v2 must expose a testable prompt builder"

    schema_config = load_schema_config()
    ocr_evidence = [{"image_index": 1, "ocr_tokens": [{"id": "p1_t001"}]}]
    layout_evidence = {"1": {"lines": [], "pairs": [], "records": []}}

    prompt = builder(schema_config, ocr_evidence, layout_evidence)
    compact_schema = json.dumps(
        schema_config["schema"],
        ensure_ascii=False,
        separators=(",", ":"),
    )

    assert f"JSON_SCHEMA={compact_schema}" in prompt
    assert '"required":["schema_version","pages","warnings"]' in prompt
    assert '"material_id"' in prompt
    assert '"formula_no"' in prompt
    assert '"AUTO_ACCEPT"' in prompt
    assert '"maximum":1' in prompt
    assert "source_image_index 必须从 1 开始" in prompt
    assert "bbox 必须使用 0 到 1 的归一化坐标" in prompt
    assert 'OCR=[{"image_index": 1' in prompt
    assert 'LAYOUT={"1":' in prompt
