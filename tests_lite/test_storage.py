"""存储模块测试。"""


import pytest

from lite_app.storage import sanitize_filename


class TestSanitizeFilename:
    def test_normal_name(self):
        assert sanitize_filename("photo.jpg") == "photo.jpg"

    def test_path_traversal(self):
        assert sanitize_filename("../../etc/passwd") == "passwd"

    def test_windows_path(self):
        result = sanitize_filename("C:\\Users\\test\\file.jpg")
        assert "\\" not in result
        assert "file.jpg" in result

    def test_dotdot(self):
        result = sanitize_filename("..")
        assert ".." not in result

    def test_empty(self):
        result = sanitize_filename("")
        assert result == "upload"

    def test_slash_removal(self):
        result = sanitize_filename("a/b/c.jpg")
        assert "/" not in result


class TestJobStorage:
    def test_create_job(self, storage):
        job = storage.create_job(rotation="auto")
        assert job["id"]
        assert job["status"] == "UPLOADED"
        assert job["rotation"] == "auto"
        assert job["images"] == []

    def test_create_job_unique_ids(self, storage):
        job1 = storage.create_job()
        job2 = storage.create_job()
        assert job1["id"] != job2["id"]

    def test_get_job(self, storage):
        job = storage.create_job()
        loaded = storage.get_job(job["id"])
        assert loaded["id"] == job["id"]
        assert loaded["status"] == "UPLOADED"

    def test_get_nonexistent_job(self, storage):
        with pytest.raises(FileNotFoundError):
            storage.get_job("20000101-000000-000000")

    def test_save_and_load_result(self, storage):
        job = storage.create_job()
        result = {"page_heading": "test", "records": [], "warnings": []}
        storage.save_result(job["id"], result)
        loaded = storage.load_result(job["id"])
        assert loaded == result

    def test_load_result_not_exists(self, storage):
        job = storage.create_job()
        assert storage.load_result(job["id"]) is None

    def test_save_upload(self, storage):
        job = storage.create_job()
        info = storage.save_upload(job["id"], 1, "test.jpg", b"fake data")
        assert info["original_name"] == "test.jpg"
        assert info["source"] == "source/source_01_test.jpg"
        assert info["size_bytes"] == 9
        # 验证文件存在
        job_dir = storage.get_job_dir(job["id"])
        assert (job_dir / info["source"]).exists()

    def test_multiple_uploads(self, storage):
        job = storage.create_job()
        storage.save_upload(job["id"], 1, "a.jpg", b"data1")
        storage.save_upload(job["id"], 2, "b.png", b"data2")
        job_dir = storage.get_job_dir(job["id"])
        assert (job_dir / "source" / "source_01_a.jpg").exists()
        assert (job_dir / "source" / "source_02_b.png").exists()

    def test_atomic_write_no_tmp_residue(self, storage):
        job = storage.create_job()
        job_dir = storage.get_job_dir(job["id"])
        tmp_files = list(job_dir.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_list_jobs_order(self, storage):
        job1 = storage.create_job()
        job2 = storage.create_job()
        jobs = storage.list_jobs()
        assert len(jobs) == 2
        # 两个任务都在列表中
        job_ids = {j["id"] for j in jobs}
        assert job1["id"] in job_ids
        assert job2["id"] in job_ids

    def test_list_jobs_skips_corrupted(self, storage, tmp_jobs_dir):
        # 创建一个损坏的任务目录
        bad_dir = tmp_jobs_dir / "bad-job"
        bad_dir.mkdir()
        (bad_dir / "job.json").write_text("not json{{{", encoding="utf-8")
        # 正常任务
        storage.create_job()
        jobs = storage.list_jobs()
        assert len(jobs) == 1

    def test_update_status(self, storage):
        job = storage.create_job()
        updated = storage.update_status(job["id"], "RECOGNIZING", "正在识别...")
        assert updated["status"] == "RECOGNIZING"
        assert updated["status_message"] == "正在识别..."

    def test_save_raw_response(self, storage):
        job = storage.create_job()
        storage.save_raw_response(job["id"], '{"test": true}')
        job_dir = storage.get_job_dir(job["id"])
        content = (job_dir / "raw_response.txt").read_text(encoding="utf-8")
        assert content == '{"test": true}'

    def test_file_exists(self, storage):
        job = storage.create_job()
        saved = storage.save_upload(job["id"], 1, "test.jpg", b"data")
        assert saved["source"] == "source/source_01_test.jpg"
        assert storage.file_exists(job["id"], saved["source"])
        assert storage.get_file_path(job["id"], saved["source"]).read_bytes() == b"data"
        assert not storage.file_exists(job["id"], "nonexistent.jpg")

    def test_get_file_path_traversal_blocked(self, storage):
        job = storage.create_job()
        with pytest.raises((ValueError, FileNotFoundError)):
            storage.get_file_path(job["id"], "../../etc/passwd")

    @pytest.mark.parametrize("job_id", [".", "", " ", "..", "not-a-job"])
    def test_invalid_job_ids_cannot_resolve_jobs_root(self, storage, job_id):
        with pytest.raises(ValueError):
            storage.get_job_dir(job_id)

    def test_invalid_job_id_cannot_read_another_job(self, storage):
        other = storage.create_job()
        saved = storage.save_upload(other["id"], 1, "secret.jpg", b"private")
        with pytest.raises(ValueError):
            storage.get_file_path(".", f"{other['id']}/{saved['source']}")

    def test_json_utf8_encoding(self, storage):
        job = storage.create_job()
        result = {"page_heading": "中文测试", "records": [], "warnings": []}
        storage.save_result(job["id"], result)
        job_dir = storage.get_job_dir(job["id"])
        raw = (job_dir / "result.json").read_text(encoding="utf-8")
        assert "中文测试" in raw
        assert "\\u" not in raw
