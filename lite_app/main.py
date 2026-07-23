"""FastAPI 页面与 API 路由。"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import get_config, load_schema_config
from .exporter import ExportError, export_job
from .pipeline import PipelineError, analyze_job, validate_result
from .providers import VisionProviderError
from .storage import JobStorage

logger = logging.getLogger(__name__)

app = FastAPI(title="daily-record-ocr-lite")

# 静态文件和模板
_BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=str(_BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))


def _get_storage() -> JobStorage:
    return JobStorage()


# ─── 健康检查 ───────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "ok", "app": "daily-record-ocr-lite"}


@app.get("/api/engine-status")
async def engine_status():
    from .ocr.manager import OCRModelManager
    ocr_mgr = OCRModelManager()
    cfg = get_config()
    vision_cfg = cfg.vision
    return {
        "ocr": ocr_mgr.get_status(),
        "vision": {
            "configured": bool(vision_cfg.get("base_url")),
            "provider": vision_cfg.get("provider", "mock"),
            "model": vision_cfg.get("model", ""),
        },
        "queue": {
            "pending": 0,
            "running_job_id": None,
        },
    }


# ─── 首页 ───────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    storage = _get_storage()
    jobs = storage.list_jobs()[:20]
    return templates.TemplateResponse(
        request, "index.html", {"jobs": jobs}
    )


# ─── 创建任务并识别 ─────────────────────────────────────────


@app.post("/jobs")
async def create_job(
    files: list[UploadFile] = File(...),
    rotation: str = Form("auto"),
):
    import shutil
    from PIL import Image as PILImage
    import io as _io

    cfg = get_config()
    storage = _get_storage()

    # 校验旋转值
    valid_rotations = {"auto", "0", "90cw", "90ccw", "180"}
    if rotation not in valid_rotations:
        raise HTTPException(
            status_code=400,
            detail=f"无效的旋转设置: {rotation}。允许: {', '.join(sorted(valid_rotations))}",
        )

    # 校验文件
    if not files:
        raise HTTPException(status_code=400, detail="请至少上传一张图片。")

    max_bytes = cfg.max_upload_mb * 1024 * 1024
    total_size = 0

    # 先读取并验证所有文件（在创建任务之前）
    validated_files: list[tuple[str, bytes]] = []
    for f in files:
        if not f.filename:
            raise HTTPException(status_code=400, detail="文件名不能为空。")
        ext = Path(f.filename).suffix.lower()
        if ext not in cfg.allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件类型: {ext}。允许: {', '.join(cfg.allowed_extensions)}",
            )
        content = await f.read()
        if not content:
            raise HTTPException(status_code=400, detail=f"文件为空: {f.filename}")
        total_size += len(content)
        if total_size > max_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"上传文件总大小超过限制 ({cfg.max_upload_mb}MB)。",
            )
        # Pillow 预验证：确认是有效图片
        try:
            img = PILImage.open(_io.BytesIO(content))
            img.verify()
        except Exception:
            raise HTTPException(
                status_code=400,
                detail=f"文件不是可识别的图片: {f.filename}",
            )
        validated_files.append((f.filename, content))

    # 创建任务
    job = storage.create_job(rotation=rotation)
    job_id = job["id"]

    # 保存上传文件
    try:
        for i, (filename, content) in enumerate(validated_files, 1):
            img_info = storage.save_upload(job_id, i, filename, content)
            job["images"].append(img_info)
        storage.save_job(job)
    except Exception as e:
        # 清理失败的任务目录
        try:
            shutil.rmtree(storage.get_job_dir(job_id), ignore_errors=True)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"文件保存失败: {e}")

    # 执行识别（双引擎 pipeline）
    try:
        from .pipeline_v2 import analyze_job_v2, PipelineError as PipelineErrorV2
        from .ocr.manager import OCRModelManager
        # 配置 OCR 管理器
        ocr_mgr = OCRModelManager()
        ocr_cfg = cfg.get("recognition", {})
        if not ocr_mgr._config:
            ocr_mgr.configure({
                "enabled": True,
                "provider": "mock",
                "device": "cpu",
                "tier": "medium",
                "minimum_score": 0.45,
            })
        await analyze_job_v2(job_id, storage)
    except Exception as e:
        logger.warning("任务 %s 双引擎识别失败，回退旧 pipeline: %s", job_id, e)
        try:
            await analyze_job(job_id, storage)
        except (PipelineError, VisionProviderError) as e2:
            logger.warning("任务 %s 识别失败: %s", job_id, e2)
        except Exception:
            logger.exception("任务 %s 未知错误", job_id)

    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)


# ─── 任务详情 ───────────────────────────────────────────────


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail(job_id: str, request: Request):
    storage = _get_storage()
    try:
        job = storage.get_job(job_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="任务不存在。")

    result = storage.load_result(job_id)
    result_json = ""
    if result:
        result_json = json.dumps(result, ensure_ascii=False, indent=2)

    return templates.TemplateResponse(
        request,
        "job.html",
        {
            "job": job,
            "result_json": result_json,
        },
    )


# ─── 重新识别 ───────────────────────────────────────────────


@app.post("/jobs/{job_id}/analyze")
async def reanalyze(job_id: str):
    storage = _get_storage()
    try:
        storage.get_job(job_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="任务不存在。")

    try:
        await analyze_job(job_id, storage)
    except (PipelineError, VisionProviderError) as exc:
        logger.warning("任务 %s 重新识别失败: %s", job_id, exc)
    except Exception:
        logger.exception("任务 %s 重新识别发生未知错误", job_id)

    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)


# ─── 保存人工修改 ───────────────────────────────────────────


@app.post("/api/jobs/{job_id}/result")
async def save_result(job_id: str, request: Request):
    storage = _get_storage()
    try:
        job = storage.get_job(job_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="任务不存在。")

    body = await request.body()
    try:
        result = json.loads(body)
    except json.JSONDecodeError as e:
        return JSONResponse(
            status_code=400,
            content={"status": "ERROR", "validation_errors": [f"JSON 格式错误: {e}"]},
        )

    if not isinstance(result, dict):
        return JSONResponse(
            status_code=400,
            content={"status": "ERROR", "validation_errors": ["结果必须是 JSON 对象。"]},
        )

    # Schema 校验
    try:
        schema_config = load_schema_config()
        schema = schema_config.get("schema", {})
        errors = validate_result(result, schema)
    except Exception as e:
        errors = [f"校验配置错误: {e}"]

    # 保存
    storage.save_result(job_id, result)
    job["validation_errors"] = errors
    if errors:
        job["status"] = "NEED_REVIEW"
        job["status_message"] = f"已保存，但有 {len(errors)} 个校验问题。"
    else:
        job["status"] = "READY"
        job["status_message"] = "已保存，校验通过。"
    storage.save_job(job)

    return {"status": job["status"], "validation_errors": errors}


# ─── 导出 ───────────────────────────────────────────────────


@app.post("/jobs/{job_id}/export")
async def export(job_id: str):
    storage = _get_storage()
    try:
        storage.get_job(job_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="任务不存在。")

    try:
        export_job(job_id, storage)
    except ExportError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导出失败: {e}")

    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)


# ─── 文件查看和下载 ─────────────────────────────────────────


@app.get("/jobs/{job_id}/files/{filename}")
async def download_file(job_id: str, filename: str):
    storage = _get_storage()
    try:
        file_path = storage.get_file_path(job_id, filename)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))

    # 判断是图片还是其他文件
    ext = file_path.suffix.lower()
    mime_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }
    if ext in mime_map:
        return FileResponse(file_path, media_type=mime_map[ext])
    elif ext == ".xlsm":
        return FileResponse(
            file_path,
            media_type="application/vnd.ms-excel.sheet.macroEnabled.12",
            filename=filename,
        )
    elif ext == ".xlsx":
        return FileResponse(
            file_path,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=filename,
        )
    else:
        return FileResponse(file_path, filename=filename)


# ─── 字段级 API ─────────────────────────────────────────────


@app.get("/api/jobs/{job_id}")
async def get_job_api(job_id: str):
    """获取任务状态（JSON API，供前端轮询）。"""
    storage = _get_storage()
    try:
        job = storage.get_job(job_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="任务不存在。")
    return job


@app.post("/api/jobs/{job_id}/fields/{field_id}")
async def update_field(job_id: str, field_id: str, request: Request):
    """人工修改单个字段值。"""
    storage = _get_storage()
    try:
        job = storage.get_job(job_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="任务不存在。")

    body = await request.json()
    new_value = body.get("value", "")
    chosen_source = body.get("source", "manual")

    # 加载融合结果
    job_dir = storage.get_job_dir(job_id)
    fusion_path = job_dir / "fusion" / "result.json"
    if not fusion_path.exists():
        raise HTTPException(status_code=400, detail="融合结果不存在。")

    fusion_data = json.loads(fusion_path.read_text(encoding="utf-8"))
    fields = fusion_data.get("fields", [])

    # 找到并更新字段
    updated = False
    old_value = ""
    for f in fields:
        if f.get("field_id") == field_id:
            old_value = f.get("final_value", "")
            f["final_value"] = new_value
            f["final_source"] = chosen_source
            f["status"] = "MANUAL_CONFIRMED"
            updated = True
            break

    if not updated:
        raise HTTPException(status_code=404, detail=f"字段不存在: {field_id}")

    # 保存
    fusion_path.write_text(json.dumps(fusion_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # 记录修正日志
    try:
        from .config import PROJECT_ROOT
        from .knowledge.database import KnowledgeDB
        db = KnowledgeDB(PROJECT_ROOT / "data" / "knowledge.sqlite3")
        db.initialize()
        from .review.corrections import CorrectionService
        svc = CorrectionService(db)
        svc.record_correction(
            job_id=job_id,
            field_id=field_id,
            field_type=body.get("field_type", ""),
            old_value=old_value,
            new_value=new_value,
            chosen_source=chosen_source,
        )
    except Exception as e:
        logger.warning("修正日志记录失败: %s", e)

    return {"status": "MANUAL_CONFIRMED", "field_id": field_id, "value": new_value}


@app.post("/api/jobs/{job_id}/confirm")
async def confirm_job(job_id: str):
    """确认所有字段，标记任务为 READY。"""
    storage = _get_storage()
    try:
        job = storage.get_job(job_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="任务不存在。")

    job["status"] = "READY"
    job["status_message"] = "所有字段已确认。"
    storage.save_job(job)
    return {"status": "READY"}


# ─── 启动入口 ───────────────────────────────────────────────


def run() -> None:
    """启动应用。"""
    import os
    import uvicorn

    cfg = get_config()
    reload = os.environ.get("APP_RELOAD", "").lower() in ("1", "true", "yes")
    uvicorn.run(
        "lite_app.main:app",
        host=cfg.host,
        port=cfg.port,
        reload=reload,
    )


if __name__ == "__main__":
    run()
