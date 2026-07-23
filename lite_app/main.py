"""FastAPI 页面与 API 路由。"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import get_config, load_schema_config, load_recognition_config
from .exporter import ExportError, export_job
from .pipeline import PipelineError, analyze_job, validate_result
from .providers import VisionProviderError
from .storage import JobStorage

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化 OCR 管理器和后台队列。"""
    try:
        from .ocr.manager import OCRModelManager
        rec_cfg = load_recognition_config()
        ocr_cfg = rec_cfg.get("ocr", {})
        mgr = OCRModelManager()
        mgr.configure({
            "enabled": str(ocr_cfg.get("enabled", "true")).lower() in ("true", "1", "yes"),
            "provider": ocr_cfg.get("provider", "mock"),
            "device": ocr_cfg.get("device", "cpu"),
            "tier": ocr_cfg.get("tier", "medium"),
            "minimum_score": float(ocr_cfg.get("minimum_score", 0.45)),
            "use_textline_orientation": ocr_cfg.get("use_textline_orientation", True),
        })
        logger.info("OCR 管理器已配置: provider=%s", ocr_cfg.get("provider", "mock"))
    except Exception as e:
        logger.warning("OCR 管理器初始化失败（降级运行）: %s", e)

    # 启动后台任务队列
    from .jobs import get_task_queue
    queue = get_task_queue()
    queue.set_handler(_process_job_background)
    await queue.start()

    yield

    await queue.stop()


async def _process_job_background(job_id: str) -> None:
    """后台处理单个任务：双引擎 pipeline，失败时回退旧 pipeline。"""
    storage = _get_storage()
    try:
        from .pipeline_v2 import analyze_job_v2
        await analyze_job_v2(job_id, storage)
    except Exception as e:
        logger.warning("任务 %s 双引擎识别失败，回退旧 pipeline: %s", job_id, e)
        try:
            await analyze_job(job_id, storage)
        except (PipelineError, VisionProviderError) as e2:
            logger.warning("任务 %s 识别失败: %s", job_id, e2)
        except Exception:
            logger.exception("任务 %s 未知错误", job_id)


app = FastAPI(title="daily-record-ocr-lite", lifespan=lifespan)

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

    # 提交到后台队列（非阻塞）
    from .jobs import get_task_queue
    queue = get_task_queue()
    await queue.submit(job_id)

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

    # 提交到后台队列重新识别
    from .jobs import get_task_queue
    queue = get_task_queue()
    await queue.submit(job_id)

    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)


@app.post("/api/jobs/{job_id}/mode")
async def switch_mode(job_id: str, request: Request):
    """切换识别模式（freeform/template/auto）并重新识别。"""
    storage = _get_storage()
    try:
        job = storage.get_job(job_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="任务不存在。")

    body = await request.json()
    mode = body.get("mode", "auto")
    valid_modes = {"freeform", "template", "auto"}
    if mode not in valid_modes:
        raise HTTPException(
            status_code=400,
            detail=f"无效模式: {mode}。允许: {', '.join(sorted(valid_modes))}",
        )

    job["recognition_mode"] = mode
    job["status"] = "UPLOADED"
    job["status_message"] = f"已切换为 {mode} 模式，等待重新识别。"
    storage.save_job(job)

    # 提交到后台队列
    from .jobs import get_task_queue
    queue = get_task_queue()
    await queue.submit(job_id)

    return {"status": "UPLOADED", "mode": mode}


@app.post("/api/jobs/{job_id}/reanalyze")
async def reanalyze_api(job_id: str):
    """重新识别（API 版本，提交到后台队列）。"""
    storage = _get_storage()
    try:
        job = storage.get_job(job_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="任务不存在。")

    job["status"] = "UPLOADED"
    job["status_message"] = "等待重新识别..."
    storage.save_job(job)

    from .jobs import get_task_queue
    queue = get_task_queue()
    await queue.submit(job_id)

    return {"status": "UPLOADED", "message": "已提交重新识别"}


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


@app.post("/api/jobs/{job_id}/fields/{field_id}/recheck")
async def recheck_field(job_id: str, field_id: str):
    """对单个冲突字段执行局部复核。"""
    storage = _get_storage()
    try:
        job = storage.get_job(job_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="任务不存在。")

    job_dir = storage.get_job_dir(job_id)
    fusion_path = job_dir / "fusion" / "result.json"
    if not fusion_path.exists():
        raise HTTPException(status_code=400, detail="融合结果不存在。")

    fusion_data = json.loads(fusion_path.read_text(encoding="utf-8"))
    fields = fusion_data.get("fields", [])
    target = None
    for f in fields:
        if f.get("field_id") == field_id:
            target = f
            break

    if not target:
        raise HTTPException(status_code=404, detail=f"字段不存在: {field_id}")

    # 执行局部复核（使用 OCR 管理器）
    from .ocr.manager import OCRModelManager
    from .review.recheck import crop_field_region

    # 找到对应的 OCR 图片
    ocr_img = None
    for img in job.get("images", []):
        prepared = img.get("prepared_ocr") or img.get("prepared", "")
        if prepared:
            candidate = job_dir / prepared
            if candidate.exists():
                ocr_img = candidate
                break

    if not ocr_img:
        return {"status": "no_image", "field_id": field_id}

    # 裁图
    bbox = target.get("bbox")
    if not bbox or len(bbox) != 4:
        # 尝试从候选中获取
        for c in target.get("candidates", []):
            if c.get("bbox"):
                bbox = c["bbox"]
                break

    crops_dir = job_dir / "crops"
    if bbox:
        try:
            crop_field_region(ocr_img, bbox, crops_dir, field_id)
        except Exception as e:
            logger.warning("裁图失败: %s", e)

    # 局部 OCR
    ocr_mgr = OCRModelManager()
    crop_path = crops_dir / f"{field_id}_context.jpg"
    local_texts = []
    if crop_path.exists():
        try:
            import asyncio
            page = await asyncio.to_thread(ocr_mgr.get_provider().recognize, crop_path)
            local_texts = [t.text for t in page.tokens]
        except Exception as e:
            logger.warning("局部 OCR 失败: %s", e)

    target["local_ocr_texts"] = local_texts
    target["recheck_done"] = True

    # 保存更新
    fusion_path.write_text(json.dumps(fusion_data, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "status": "recheck_done",
        "field_id": field_id,
        "local_ocr_texts": local_texts,
    }


# ─── 知识库管理 ─────────────────────────────────────────────


@app.get("/knowledge", response_class=HTMLResponse)
async def knowledge_page(request: Request):
    """知识库管理页面。"""
    from .config import PROJECT_ROOT
    from .knowledge.database import KnowledgeDB
    db = KnowledgeDB(PROJECT_ROOT / "data" / "knowledge.sqlite3")
    db.initialize()
    materials = db.get_all_materials()
    formulas = db.get_all_formulas()
    return templates.TemplateResponse(
        request, "knowledge.html", {"materials": materials, "formulas": formulas}
    )


@app.post("/knowledge/materials")
async def add_material(request: Request):
    """添加物料。"""
    from .config import PROJECT_ROOT
    from .knowledge.database import KnowledgeDB
    body = await request.json()
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="物料名称不能为空。")

    db = KnowledgeDB(PROJECT_ROOT / "data" / "knowledge.sqlite3")
    db.initialize()
    mid = db.add_material(name, body.get("category", ""), body.get("unit", ""))

    # 添加别名
    for alias in body.get("aliases", []):
        if alias.strip():
            db.add_alias(mid, alias.strip(), alias_type="manual", source="web")

    return {"id": mid, "name": name}


@app.post("/knowledge/import")
async def import_knowledge(file: UploadFile = File(...)):
    """从 Excel/CSV 导入物料和配方到知识库。"""
    from .config import PROJECT_ROOT
    from .knowledge.database import KnowledgeDB
    import csv
    import io as _io

    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空。")

    ext = Path(file.filename).suffix.lower()
    if ext not in (".xlsx", ".csv"):
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}。允许: .xlsx, .csv")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空。")

    db = KnowledgeDB(PROJECT_ROOT / "data" / "knowledge.sqlite3")
    db.initialize()

    imported_count = 0

    try:
        if ext == ".csv":
            text = content.decode("utf-8-sig")
            reader = csv.DictReader(_io.StringIO(text))
            for row in reader:
                name = (row.get("物料名称") or row.get("name") or row.get("material") or "").strip()
                if name:
                    unit = (row.get("单位") or row.get("unit") or "").strip()
                    category = (row.get("分类") or row.get("category") or "").strip()
                    db.add_material(name, category, unit)
                    # 别名
                    alias_str = (row.get("别名") or row.get("aliases") or "").strip()
                    if alias_str:
                        mid = db.add_material(name, category, unit)
                        for alias in alias_str.replace("；", ";").split(";"):
                            if alias.strip():
                                db.add_alias(mid, alias.strip(), alias_type="import", source="csv")
                    imported_count += 1
        else:
            # xlsx
            from openpyxl import load_workbook
            import io as _io2
            wb = load_workbook(_io2.BytesIO(content), read_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))
            if len(rows) < 2:
                raise HTTPException(status_code=400, detail="文件行数不足。")

            # 自动识别列
            headers = [str(h or "").strip() for h in rows[0]]
            name_col = None
            unit_col = None
            category_col = None
            alias_col = None
            for i, h in enumerate(headers):
                hl = h.lower()
                if "物料" in h or "名称" in h or hl == "name" or hl == "material":
                    name_col = i
                elif "单位" in h or hl == "unit":
                    unit_col = i
                elif "分类" in h or hl == "category":
                    category_col = i
                elif "别名" in h or hl == "aliases":
                    alias_col = i

            if name_col is None:
                name_col = 0  # 默认第一列

            for row in rows[1:]:
                if not row or len(row) <= name_col:
                    continue
                name = str(row[name_col] or "").strip()
                if not name:
                    continue
                unit = str(row[unit_col] or "").strip() if unit_col is not None and len(row) > unit_col else ""
                category = str(row[category_col] or "").strip() if category_col is not None and len(row) > category_col else ""
                mid = db.add_material(name, category, unit)
                if alias_col is not None and len(row) > alias_col:
                    alias_str = str(row[alias_col] or "").strip()
                    if alias_str:
                        for alias in alias_str.replace("；", ";").split(";"):
                            if alias.strip():
                                db.add_alias(mid, alias.strip(), alias_type="import", source="xlsx")
                imported_count += 1
            wb.close()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"导入失败: {e}")

    return {"imported": imported_count, "message": f"成功导入 {imported_count} 条物料记录。"}


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
