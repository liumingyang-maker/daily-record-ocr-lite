"""文件任务存储：文件夹 + JSON 任务管理。"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import get_config
from .status import JobStatus

logger = logging.getLogger(__name__)
_JOB_ID_PATTERN = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _generate_job_id() -> str:
    """生成任务编号：YYYYMMDD-HHMMSS-随机六位十六进制。"""
    now = datetime.now()
    rand = secrets.token_hex(3)
    return f"{now.strftime('%Y%m%d-%H%M%S')}-{rand}"


def sanitize_filename(name: str) -> str:
    """安全清洗文件名：只保留 basename，去除路径和危险字符。"""
    # 只取文件名部分
    name = os.path.basename(name)
    # 去除路径分隔符（防止 Windows 和 Unix 穿越）
    name = name.replace("/", "").replace("\\", "")
    # 去除 ..
    name = name.replace("..", "")
    # 如果清洗后为空，给默认名
    if not name or name in (".", ".."):
        name = "upload"
    return name


class RequiredDataError(RuntimeError):
    """A required persisted artifact is missing, unreadable, or malformed."""


def write_json_atomic(path: Path, data: Any) -> None:
    """原子写入 JSON：先写临时文件再替换。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), suffix=".tmp", prefix=".job_"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(path))
    except BaseException:
        # 清理临时文件
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), suffix=".tmp", prefix=".text_"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, str(path))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def write_bytes_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), suffix=".tmp", prefix=".bytes_"
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, str(path))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def read_json_required(path: Path) -> Any:
    if not path.exists():
        raise RequiredDataError(f"必需文件不存在: {path}")
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise RequiredDataError(f"必需文件无法读取: {path}: {exc}") from exc


def read_json_optional(path: Path) -> Any | None:
    if not path.exists():
        return None
    return read_json_required(path)


_atomic_write_json = write_json_atomic


class JobStorage:
    """任务存储管理器。"""

    def __init__(self, jobs_dir: Path | None = None) -> None:
        if jobs_dir is None:
            jobs_dir = get_config().jobs_dir
        self.jobs_dir = jobs_dir
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    def _job_dir(self, job_id: str) -> Path:
        """获取任务目录，并验证安全性。"""
        if not _JOB_ID_PATTERN.fullmatch(str(job_id)):
            raise ValueError(f"非法任务 ID: {job_id}")
        root = self.jobs_dir.resolve()
        candidate = (root / job_id).resolve()
        if candidate == root:
            raise ValueError(f"非法任务 ID: {job_id}")
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"非法任务 ID: {job_id}") from exc
        return candidate

    def create_job(
        self, rotation: str = "auto", rotations: list[str] | None = None
    ) -> dict[str, Any]:
        """创建新任务。"""
        job_id = _generate_job_id()
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)

        now = _now_iso()
        job_data = {
            "id": job_id,
            "status": JobStatus.UPLOADED,
            "created_at": now,
            "updated_at": now,
            "rotation": rotation,
            "rotations": list(rotations or []),
            "images": [],
            "provider": "",
            "model": "",
            "status_message": "",
            "validation_errors": [],
            "error": "",
            "export_file": None,
        }
        write_json_atomic(job_dir / "job.json", job_data)
        self._append_status_event(
            job_dir,
            from_status=None,
            to_status=JobStatus.UPLOADED,
            message="任务已创建",
        )
        logger.info("创建任务: %s", job_id)
        return job_data

    def get_job(self, job_id: str) -> dict[str, Any]:
        """读取任务数据。"""
        job_dir = self._job_dir(job_id)
        job_file = job_dir / "job.json"
        if not job_file.exists():
            raise FileNotFoundError(f"任务不存在: {job_id}")
        with open(job_file, encoding="utf-8") as f:
            return json.load(f)

    def save_job(self, job_data: dict[str, Any]) -> None:
        """保存任务数据。"""
        job_id = job_data["id"]
        job_dir = self._job_dir(job_id)
        previous = read_json_optional(job_dir / "job.json")
        old_status = previous.get("status") if isinstance(previous, dict) else None
        new_status = job_data.get("status")
        job_data["updated_at"] = _now_iso()
        write_json_atomic(job_dir / "job.json", job_data)
        if old_status != new_status and new_status:
            self._append_status_event(
                job_dir,
                from_status=old_status,
                to_status=str(new_status),
                message=str(job_data.get("status_message", "")),
            )

    @staticmethod
    def _append_status_event(
        job_dir: Path,
        from_status: str | None,
        to_status: str,
        message: str,
    ) -> None:
        path = job_dir / "review" / "job_events.json"
        events = read_json_optional(path)
        if not isinstance(events, list):
            events = []
        events.append(
            {
                "event": "status_changed",
                "from_status": from_status,
                "to_status": to_status,
                "reason": message,
                "message": message,
                "timestamp": _now_iso(),
            }
        )
        write_json_atomic(path, events)

    def update_status(
        self, job_id: str, status: str, message: str = ""
    ) -> dict[str, Any]:
        """更新任务状态。"""
        job = self.get_job(job_id)
        job["status"] = status
        if message:
            job["status_message"] = message
        self.save_job(job)
        logger.info("任务 %s 状态变更: %s", job_id, status)
        return job

    def get_job_dir(self, job_id: str) -> Path:
        """获取任务目录路径。"""
        return self._job_dir(job_id)

    def save_upload(
        self, job_id: str, index: int, original_name: str, content: bytes
    ) -> dict[str, Any]:
        """保存上传文件到任务目录。"""
        job_dir = self._job_dir(job_id)
        safe_name = sanitize_filename(original_name)
        source_name = f"source_{index:02d}_{safe_name}"
        relative_path = Path("source") / source_name
        file_path = job_dir / relative_path
        write_bytes_atomic(file_path, content)
        return {
            "original_name": original_name,
            "source": relative_path.as_posix(),
            "prepared": "",
            "size_bytes": len(content),
        }

    def save_result(self, job_id: str, result: dict[str, Any]) -> None:
        """保存识别结果。"""
        job_dir = self._job_dir(job_id)
        write_json_atomic(job_dir / "result.json", result)

    def load_result(self, job_id: str) -> dict[str, Any] | None:
        """加载识别结果。"""
        job_dir = self._job_dir(job_id)
        result_file = job_dir / "result.json"
        if not result_file.exists():
            return None
        with open(result_file, encoding="utf-8") as f:
            return json.load(f)

    def save_raw_response(self, job_id: str, text: str) -> None:
        """保存原始模型响应。"""
        job_dir = self._job_dir(job_id)
        write_text_atomic(job_dir / "raw_response.txt", text)

    def list_jobs(self) -> list[dict[str, Any]]:
        """列出所有任务，按创建时间倒序。"""
        jobs: list[dict[str, Any]] = []
        if not self.jobs_dir.exists():
            return jobs
        for entry in self.jobs_dir.iterdir():
            if not entry.is_dir():
                continue
            job_file = entry / "job.json"
            if not job_file.exists():
                continue
            try:
                with open(job_file, encoding="utf-8") as f:
                    job = json.load(f)
                jobs.append(job)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("跳过损坏的任务 %s: %s", entry.name, e)
                continue
        # 按创建时间倒序
        jobs.sort(key=lambda j: j.get("created_at", ""), reverse=True)
        return jobs

    def file_exists(self, job_id: str, filename: str) -> bool:
        """检查任务目录中文件是否存在。"""
        try:
            self.get_file_path(job_id, filename)
        except (FileNotFoundError, ValueError):
            return False
        return True

    def get_file_path(self, job_id: str, filename: str) -> Path:
        """获取任务目录中文件的安全路径。"""
        job_dir = self._job_dir(job_id)
        relative = Path(str(filename).replace("\\", "/"))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"非法文件路径: {filename}")
        file_path = (job_dir / relative).resolve()
        # 再次确认在任务目录下
        try:
            file_path.relative_to(job_dir.resolve())
        except ValueError as exc:
            raise ValueError(f"非法文件路径: {filename}") from exc
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {filename}")
        return file_path
