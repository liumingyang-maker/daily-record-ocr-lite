"""Web 端到端测试。"""

import io
import json
import pytest
from pathlib import Path
from PIL import Image

from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """创建使用临时目录的测试客户端。"""
    import os
    jobs_dir = tmp_path / "test_jobs"
    jobs_dir.mkdir()
    monkeypatch.setenv("JOBS_DIR", str(jobs_dir))
    monkeypatch.setenv("VISION_PROVIDER", "mock")

    from lite_app.config import clear_config_cache
    clear_config_cache()

    from lite_app.main import app
    with TestClient(app) as c:
        yield c

    clear_config_cache()


def _make_test_image() -> bytes:
    """生成测试图片字节。"""
    img = Image.new("RGB", (100, 80), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


class TestHealthCheck:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["app"] == "daily-record-ocr-lite"


class TestIndex:
    def test_index_page(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "手写记录" in resp.text


class TestFullFlow:
    def test_upload_recognize_edit_export_download(self, client):
        """完整闭环：上传 -> 识别 -> 编辑 -> 导出 -> 下载。"""
        img_data = _make_test_image()

        # 1. 上传两张图片
        resp = client.post(
            "/jobs",
            files=[
                ("files", ("photo1.jpg", img_data, "image/jpeg")),
                ("files", ("photo2.jpg", img_data, "image/jpeg")),
            ],
            data={"rotation": "0"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        location = resp.headers["location"]
        assert "/jobs/" in location
        job_id = location.split("/jobs/")[1]

        # 2. 访问任务详情
        resp = client.get(f"/jobs/{job_id}")
        assert resp.status_code == 200
        assert job_id in resp.text

        # 3. 验证识别结果存在（mock provider）
        resp = client.get(f"/jobs/{job_id}")
        assert "page_heading" in resp.text or "json-editor" in resp.text

        # 4. 保存修改后的 JSON
        edited_result = {
            "page_heading": "修改后的标题",
            "records": [
                {
                    "source_image_indexes": [1],
                    "record_date": "24.7.10",
                    "title": "修改配方",
                    "materials": [
                        {"name": "PA66", "amount": "65", "unit": "kg", "confidence": 0.95}
                    ],
                    "process_parameters": [],
                    "notes": "",
                    "confidence": 0.9,
                    "warnings": [],
                }
            ],
            "warnings": [],
        }
        resp = client.post(
            f"/api/jobs/{job_id}/result",
            content=json.dumps(edited_result, ensure_ascii=False),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "READY"
        assert data["validation_errors"] == []

        # 5. 导出 Excel
        resp = client.post(f"/jobs/{job_id}/export", follow_redirects=False)
        assert resp.status_code == 303

        # 6. 验证任务状态更新
        resp = client.get(f"/jobs/{job_id}")
        assert resp.status_code == 200

        # 7. 下载 Excel
        # 先获取 export_file 名
        from lite_app.storage import JobStorage
        storage = JobStorage()
        job = storage.get_job(job_id)
        assert job["export_file"] is not None

        resp = client.get(f"/jobs/{job_id}/files/{job['export_file']}")
        assert resp.status_code == 200
        assert len(resp.content) > 0

    def test_upload_no_files(self, client):
        """无文件上传报错。"""
        resp = client.post("/jobs", files=[], data={"rotation": "auto"})
        assert resp.status_code == 400 or resp.status_code == 422

    def test_upload_bad_extension(self, client):
        """不支持的文件类型。"""
        resp = client.post(
            "/jobs",
            files=[("files", ("test.txt", b"hello", "text/plain"))],
            data={"rotation": "auto"},
        )
        assert resp.status_code == 400

    def test_nonexistent_job_404(self, client):
        resp = client.get("/jobs/nonexistent-id-12345")
        assert resp.status_code == 404

    def test_save_invalid_json(self, client):
        """保存非法 JSON。"""
        img_data = _make_test_image()
        resp = client.post(
            "/jobs",
            files=[("files", ("p.jpg", img_data, "image/jpeg"))],
            data={"rotation": "0"},
            follow_redirects=False,
        )
        job_id = resp.headers["location"].split("/jobs/")[1]

        resp = client.post(
            f"/api/jobs/{job_id}/result",
            content="not valid json{{{",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    def test_reanalyze(self, client):
        """重新识别。"""
        img_data = _make_test_image()
        resp = client.post(
            "/jobs",
            files=[("files", ("p.jpg", img_data, "image/jpeg"))],
            data={"rotation": "0"},
            follow_redirects=False,
        )
        job_id = resp.headers["location"].split("/jobs/")[1]

        resp = client.post(f"/jobs/{job_id}/analyze", follow_redirects=False)
        assert resp.status_code == 303

        # 验证任务仍然正常
        resp = client.get(f"/jobs/{job_id}")
        assert resp.status_code == 200

    def test_file_download_404(self, client):
        """下载不存在的文件。"""
        img_data = _make_test_image()
        resp = client.post(
            "/jobs",
            files=[("files", ("p.jpg", img_data, "image/jpeg"))],
            data={"rotation": "0"},
            follow_redirects=False,
        )
        job_id = resp.headers["location"].split("/jobs/")[1]

        resp = client.get(f"/jobs/{job_id}/files/nonexistent.xlsx")
        assert resp.status_code == 404
