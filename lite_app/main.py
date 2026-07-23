"""FastAPI 页面与 API 路由。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import get_config, load_schema_config
from .exporter import ExportError, export_job
from .pipeline import PipelineError, analyze_job, extract_json, validate_result
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
    cfg = get_config()
    storage = _get_storage()

    # 校验文件
    if not files:
        raise HTTPException(status_code=400, detail="请至少上传一张图片。")

    max_bytes = cfg.max_upload_mb * 1024 * 1024
    total_size = 0

    for f in files:
        if not f.filename:
            raise HTTPException(status_code=400, detail="文件名不能为空。")
        ext = Path(f.filename).suffix.lower()
        if ext not in cfg.allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件类型: {ext}。允许: {', '.join(cfg.allowed_extensions)}",
            )

    # 创建任务
    job = storage.create_job(rotation=rotation)
    job_id = job["id"]

    # 保存上传文件
    try:
        for i, f in enumerate(files, 1):
            content = await f.read()
            if not content:
                raise HTTPException(status_code=400, detail=f"文件为空: {f.filename}")
            total_size += len(content)
            if total_size > max_bytes:
                raise HTTPException(
                    status_code=400,
                    detail=f"上传文件总大小超过限制 ({cfg.max_upload_mb}MB)。",
                )
            img_info = storage.save_upload(job_id, i, f.filename or "upload.jpg", content)
            job["images"].append(img_info)
        storage.save_job(job)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件保存失败: {e}")

    # 执行识别
    try:
        await analyze_job(job_id, storage)
    except (PipelineError, VisionProviderError) as e:
        # 识别失败但任务已创建，重定向到详情页显示错误
        logger.warning("任务 %s 识别失败: %s", job_id, e)
    except Exception as e:
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
    except (PipelineError, VisionProviderError):
        pass  # 状态已在 pipeline 中更新
    except Exception:
        pass

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
    if ext in (".jpg", ".jpeg", ".png", ".webp"):
        return FileResponse(file_path, media_type="image/jpeg")
    elif ext in (".xlsx", ".xlsm"):
        return FileResponse(
            file_path,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=filename,
        )
    else:
        return FileResponse(file_path, filename=filename)


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
