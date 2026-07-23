"""识别 Pipeline：提示词构建、模型调用、JSON 解析、Schema 校验。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .config import get_config, load_schema_config
from .image_utils import ImageProcessError, prepare_image
from .providers import VisionProviderError, build_provider
from .storage import JobStorage

logger = logging.getLogger(__name__)


class PipelineError(Exception):
    """Pipeline 处理错误。"""
    pass


def build_prompts(schema_config: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    """
    从 record_schema.yaml 构建提示词。

    返回: (system_prompt, user_prompt, json_schema)
    """
    system_prompt = schema_config.get("system_prompt", "").strip()
    instructions = schema_config.get("instructions", "").strip()
    schema = schema_config.get("schema", {})

    # 构建 user_prompt
    schema_text = json.dumps(schema, ensure_ascii=False, indent=2)
    user_prompt = f"""{instructions}

请严格按照以下 JSON Schema 返回结果：

{schema_text}

重要提醒：
- 只返回一个 JSON 对象，不要输出任何解释文字。
- 不要使用 Markdown 代码块包裹。
- 看不清的内容不要猜测，使用空字符串并在 warnings 中说明。
- 数字和单位保持图片原样。"""

    return system_prompt, user_prompt, schema


def extract_json(text: str) -> dict[str, Any]:
    """
    从模型响应文本中提取 JSON 对象。

    支持：纯 JSON、```json 代码块、JSON 前后有文字。
    """
    text = text.strip()

    # 1. 直接尝试解析
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
        if isinstance(result, list):
            raise PipelineError("模型返回了 JSON 数组，但需要的是 JSON 对象。")
    except json.JSONDecodeError:
        pass

    # 2. 尝试剥离 Markdown 代码块
    fence_result = _extract_from_fence(text)
    if fence_result is not None:
        return fence_result

    # 3. 从第一个 { 开始尝试 raw_decode
    brace_result = _extract_from_brace(text)
    if brace_result is not None:
        return brace_result

    raise PipelineError(
        f"无法从模型响应中解析出 JSON 对象。响应前200字符: {text[:200]}"
    )


def _extract_from_fence(text: str) -> dict[str, Any] | None:
    """从 Markdown 代码块中提取 JSON。"""
    import re

    # 匹配 ```json ... ``` 或 ``` ... ```
    pattern = r"```(?:json)?\s*\n?(.*?)\n?\s*```"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        content = match.group(1).strip()
        try:
            result = json.loads(content)
            if isinstance(result, dict):
                return result
            if isinstance(result, list):
                raise PipelineError("模型返回了 JSON 数组，但需要的是 JSON 对象。")
        except json.JSONDecodeError:
            pass
    return None


def _extract_from_brace(text: str) -> dict[str, Any] | None:
    """遍历所有 { 位置，用 raw_decode 尝试提取首个合法顶层对象。"""
    decoder = json.JSONDecoder()
    last_error: Exception | None = None
    for i, char in enumerate(text):
        if char != "{":
            continue
        try:
            result, _ = decoder.raw_decode(text, i)
            if isinstance(result, dict):
                return result
            if isinstance(result, list):
                raise PipelineError("模型返回了 JSON 数组，但需要的是 JSON 对象。")
        except json.JSONDecodeError as e:
            last_error = e
            continue
    return None


def validate_result(
    result: dict[str, Any], schema: dict[str, Any]
) -> list[str]:
    """
    使用 Draft 2020-12 校验结果。

    返回所有错误信息列表（带 JSON 路径）。
    """
    validator = Draft202012Validator(schema)
    errors: list[str] = []
    for error in validator.iter_errors(result):
        path = ".".join(str(p) for p in error.absolute_path)
        if path:
            errors.append(f"{path}: {error.message}")
        else:
            errors.append(error.message)
    return errors


async def analyze_job(job_id: str, storage: JobStorage | None = None) -> dict[str, Any]:
    """
    完整识别流程：预处理 -> 模型调用 -> JSON 解析 -> Schema 校验。
    """
    if storage is None:
        storage = JobStorage()

    cfg = get_config()
    job = storage.get_job(job_id)
    job_dir = storage.get_job_dir(job_id)

    try:
        # 清空旧错误
        job["error"] = ""
        job["validation_errors"] = []
        job["status"] = "PREPARING"
        job["status_message"] = "正在处理图片..."
        storage.save_job(job)

        # 处理每张图片
        preprocess_cfg = cfg.preprocess
        rotation = job.get("rotation", "auto")
        prepared_files: list[str] = []

        for i, img_info in enumerate(job["images"], 1):
            source_path = job_dir / img_info["source"]
            prepared_name = f"prepared_{i:02d}.jpg"
            output_path = job_dir / prepared_name

            info = prepare_image(
                source_path, output_path, rotation=rotation, config=preprocess_cfg
            )
            img_info["prepared"] = prepared_name
            img_info["width"] = info["width"]
            img_info["height"] = info["height"]
            prepared_files.append(prepared_name)

        storage.save_job(job)

        # 进入识别阶段
        vision_cfg = cfg.vision
        provider = build_provider(vision_cfg)
        job["status"] = "RECOGNIZING"
        job["status_message"] = "正在调用视觉模型..."
        job["provider"] = vision_cfg.get("provider", "mock")
        job["model"] = vision_cfg.get("model", "")
        storage.save_job(job)

        # 构建提示词
        schema_config = load_schema_config()
        system_prompt, user_prompt, json_schema = build_prompts(schema_config)

        # 调用 provider
        image_paths = [job_dir / f for f in prepared_files]
        raw_response = await provider.analyze(
            image_paths, system_prompt, user_prompt, json_schema
        )

        # 保存原始响应
        storage.save_raw_response(job_id, raw_response)

        # 解析 JSON
        result = extract_json(raw_response)

        # Schema 校验
        validation_errors = validate_result(result, json_schema)

        # 保存结果
        storage.save_result(job_id, result)

        # 更新状态
        job["validation_errors"] = validation_errors
        if validation_errors:
            job["status"] = "NEED_REVIEW"
            job["status_message"] = f"识别完成，但有 {len(validation_errors)} 个校验问题需要确认。"
        else:
            job["status"] = "READY"
            job["status_message"] = "识别完成，结果通过校验。"

        storage.save_job(job)
        logger.info("任务 %s 识别完成: %s", job_id, job["status"])
        return job

    except (ImageProcessError, VisionProviderError, PipelineError) as e:
        job["status"] = "FAILED"
        job["error"] = str(e)
        job["status_message"] = str(e)
        storage.save_job(job)
        logger.error("任务 %s 失败: %s", job_id, e)
        raise

    except Exception as e:
        job["status"] = "FAILED"
        job["error"] = f"未知错误: {e}"
        job["status_message"] = f"未知错误: {e}"
        storage.save_job(job)
        logger.exception("任务 %s 未知错误", job_id)
        raise PipelineError(f"识别过程出错: {e}")
