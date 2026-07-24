"""Web 端到端测试。"""

import io
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image


@pytest.fixture
def client(tmp_path, monkeypatch):
    """创建使用临时目录的测试客户端。"""
    jobs_dir = tmp_path / "test_jobs"
    jobs_dir.mkdir()
    monkeypatch.setenv("JOBS_DIR", str(jobs_dir))
    monkeypatch.setenv("VISION_PROVIDER", "mock")
    monkeypatch.setenv("OCR_PROVIDER", "mock")
    monkeypatch.setenv("DEMO_MODE", "true")

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
    def _extract_job_id(self, location: str) -> str:
        """从重定向 URL 中提取 job_id。"""
        # URL 格式: /jobs/{job_id}/result 或 /jobs/{job_id}
        path = location.split("/jobs/")[1]
        return path.split("/")[0]

    def test_upload_recognize_edit_export_download(self, client):
        """完整闭环：上传 -> 识别 -> 编辑 -> 导出 -> 下载。"""
        img_data = _make_test_image()

        # 1. 上传一张图片（固定 Demo fixture 也只覆盖一页）
        resp = client.post(
            "/jobs",
            files=[
                ("files", ("photo1.jpg", img_data, "image/jpeg")),
            ],
            data={"rotation": "0"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        location = resp.headers["location"]
        assert "/jobs/" in location
        job_id = self._extract_job_id(location)

        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            state = client.get(f"/api/jobs/{job_id}").json()["status"]
            if state in {"READY", "REVIEW_REQUIRED", "FAILED", "FAILED_SCHEMA"}:
                break
            time.sleep(0.02)
        assert state == "REVIEW_REQUIRED"

        # 2. 访问任务详情
        resp = client.get(f"/jobs/{job_id}")
        assert resp.status_code == 200
        assert job_id in resp.text

        # 3. 访问分组结果页面
        resp = client.get(f"/jobs/{job_id}/result")
        assert resp.status_code == 200

        # 4. 保存修改后的 JSON
        root = Path(__file__).resolve().parents[1]
        edited_result = json.loads(
            (root / "config" / "mock_result.json").read_text("utf-8")
        )
        page = edited_result["pages"][0]
        page["company"]["raw_value"] = "修改后的标题"
        page["company"]["standard_value"] = "修改后的标题"
        formula = page["product_sections"][0]["formulas"][0]
        formula["record_date"]["value"] = "24.7.10"
        formula["materials"][0]["name"]["value"] = "PA66"
        formula["materials"][0]["amount"]["value"] = "65"
        formula["materials"][0]["unit"]["value"] = "kg"
        resp = client.post(
            f"/api/jobs/{job_id}/result",
            content=json.dumps(edited_result, ensure_ascii=False),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "REVIEW_REQUIRED"
        assert data["validation_errors"] == []

        # 5. 导出 Excel
        resp = client.post(f"/jobs/{job_id}/export", follow_redirects=False)
        assert resp.status_code == 303

        # 6. 验证任务状态更新
        resp = client.get(f"/jobs/{job_id}")
        assert resp.status_code == 200

        # 7. 下载 Excel
        from lite_app.storage import JobStorage
        storage = JobStorage()
        job = storage.get_job(job_id)
        assert job["export_file"] is not None
        assert Path(job["export_file"]).name.startswith("DEMO-")

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
        job_id = self._extract_job_id(resp.headers["location"])

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
        job_id = self._extract_job_id(resp.headers["location"])

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
        job_id = self._extract_job_id(resp.headers["location"])

        resp = client.get(f"/jobs/{job_id}/files/nonexistent.xlsx")
        assert resp.status_code == 404
