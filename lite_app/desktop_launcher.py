"""Loopback-only single-instance launcher for native desktop bundles."""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import BinaryIO

from .platform_paths import DATA_ROOT

LOOPBACK_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def validate_loopback_host(host: str) -> str:
    """Reject network-exposed desktop bindings."""
    if host != LOOPBACK_HOST:
        raise ValueError("桌面应用只允许监听 127.0.0.1")
    return host


def select_available_port(
    *, host: str = LOOPBACK_HOST, preferred: int = DEFAULT_PORT, attempts: int = 100
) -> int:
    """Return the first available loopback port starting at ``preferred``."""
    validate_loopback_host(host)
    for port in range(preferred, min(preferred + attempts, 65536)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
            try:
                candidate.bind((host, port))
            except OSError:
                continue
            return port
    raise RuntimeError("未找到可用的本机端口")


class SingleInstanceLock:
    """A small non-blocking advisory lock shared by Windows and macOS."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._handle: BinaryIO | None = None
        self._acquired = False

    def acquire(self) -> bool:
        if self._handle is not None:
            return self._acquired
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle: BinaryIO | None = None
        try:
            handle = self.path.open("a+b")
            handle.seek(0)
            if handle.read(1) == b"":
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            if handle is not None:
                handle.close()
            self._handle = None
            return False
        self._handle = handle
        self._acquired = True
        return True

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        try:
            if self._acquired:
                if sys.platform == "win32":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
            self._handle = None
            self._acquired = False

    def __enter__(self) -> SingleInstanceLock:
        if not self.acquire():
            raise RuntimeError("应用已经在运行")
        return self

    def __exit__(self, *_: object) -> None:
        self.release()


@dataclass(frozen=True)
class InstanceState:
    pid: int
    host: str
    port: int

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"


def write_instance_state(path: Path, state: InstanceState) -> None:
    """Atomically persist only safe local connection metadata."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".instance-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(asdict(state), handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def read_instance_state(path: Path) -> InstanceState | None:
    """Read a valid loopback instance state, ignoring stale or unsafe data."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        state = InstanceState(
            pid=int(payload["pid"]),
            host=str(payload["host"]),
            port=int(payload["port"]),
        )
        validate_loopback_host(state.host)
        if state.pid <= 0 or not (1 <= state.port <= 65535):
            return None
        return state
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def self_test(data_root: Path = DATA_ROOT) -> dict[str, object]:
    """Run package-safe checks without starting OCR or opening a browser."""
    root = Path(data_root)
    root.mkdir(parents=True, exist_ok=True)
    probe = root / ".desktop-write-test"
    probe.write_bytes(b"ok")
    probe.unlink()

    first = SingleInstanceLock(root / ".desktop-self-test.lock")
    second = SingleInstanceLock(root / ".desktop-self-test.lock")
    first_acquired = first.acquire()
    second_rejected = not second.acquire()
    second.release()
    first.release()
    port = select_available_port()
    return {
        "status": "OK" if first_acquired and second_rejected else "FAILED",
        "loopback_only": validate_loopback_host(LOOPBACK_HOST) == LOOPBACK_HOST,
        "single_instance": first_acquired and second_rejected,
        "data_directory_writable": True,
        "available_port": port,
    }


def smoke_test(data_root: Path = DATA_ROOT) -> dict[str, object]:
    """Start the frozen web application, verify health, then exit cleanly."""
    root = Path(data_root)
    root.mkdir(parents=True, exist_ok=True)
    lock = SingleInstanceLock(root / "desktop.lock")
    if not lock.acquire():
        return {"status": "FAILED", "error_category": "INSTANCE_ALREADY_RUNNING"}
    server = None
    thread = None
    try:
        port = select_available_port()
        _configure_runtime(root, port)
        import uvicorn

        from .main import app

        server = uvicorn.Server(
            uvicorn.Config(app, host=LOOPBACK_HOST, port=port, log_level="warning")
        )
        thread = threading.Thread(target=server.run, name="desktop-smoke-server", daemon=True)
        thread.start()
        url = f"http://{LOOPBACK_HOST}:{port}/"
        _wait_for_health(url)
        return {"status": "OK", "url": url, "loopback_only": True}
    except Exception as exc:
        return {
            "status": "FAILED",
            "error_category": "DESKTOP_SMOKE_FAILED",
            "error_type": type(exc).__name__,
        }
    finally:
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(timeout=15)
        lock.release()


def real_ocr_test(data_root: Path = DATA_ROOT) -> dict[str, object]:
    """Run one real PP-OCRv6 inference from the packaged runtime."""
    root = Path(data_root)
    probe_dir = root / "setup"
    probe_dir.mkdir(parents=True, exist_ok=True)
    image_path = probe_dir / "desktop-real-ocr.png"
    try:
        _configure_model_cache(root)
        from PIL import Image, ImageDraw, ImageFont

        from .ocr.paddleocr_v6 import PaddleOCRv6Provider

        image = Image.new("RGB", (720, 260), "white")
        draw = ImageDraw.Draw(image)
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", 42)
        except OSError:
            font = ImageFont.load_default()
        draw.text((40, 35), "PA66  60kg", fill="black", font=font)
        draw.text((40, 105), "GF30  30kg", fill="black", font=font)
        draw.text((40, 175), "Process 50Hz", fill="black", font=font)
        image.save(image_path)

        provider = PaddleOCRv6Provider(device="cpu", tier="medium")
        try:
            provider.load()
        except Exception as exc:
            return _ocr_failure("LOAD", exc)
        started = time.monotonic()
        try:
            page = provider.recognize(image_path)
        except Exception as exc:
            return _ocr_failure("INFERENCE", exc)
        latency_ms = int((time.monotonic() - started) * 1000)
        if not page.tokens:
            return {"status": "FAILED", "error_category": "NO_REAL_OCR_TOKENS"}
        return {
            "status": "OK",
            "provider": page.provider,
            "model": page.model,
            "token_count": len(page.tokens),
            "latency_ms": latency_ms,
        }
    except Exception as exc:
        return {
            "status": "FAILED",
            "error_category": "REAL_OCR_FAILED",
            "error_type": type(exc).__name__,
        }
    finally:
        try:
            image_path.unlink(missing_ok=True)
        except OSError:
            pass


def _ocr_failure(stage: str, exc: Exception) -> dict[str, object]:
    error_types: list[str] = []
    current: BaseException | None = exc
    while current is not None and len(error_types) < 4:
        error_types.append(type(current).__name__)
        current = current.__cause__ or current.__context__
    result: dict[str, object] = {
        "status": "FAILED",
        "error_category": "REAL_OCR_FAILED",
        "error_stage": stage,
        "error_types": error_types,
    }
    if os.environ.get("DESKTOP_DIAGNOSTICS", "").strip() == "1":
        result["diagnostic_preview"] = _safe_exception_preview(exc)
    return result


def _safe_exception_preview(exc: BaseException) -> str:
    parts: list[str] = []
    current: BaseException | None = exc
    while current is not None and len(parts) < 4:
        parts.append(str(current))
        current = current.__cause__ or current.__context__
    preview = " | ".join(parts)
    preview = preview.replace(str(Path.home()), "<HOME>")
    preview = re.sub(r"sk-(?:ws|sp)-[A-Za-z0-9._-]+", "<API_KEY>", preview)
    return preview[:500]


def run_desktop(data_root: Path = DATA_ROOT) -> int:
    """Start the local web application and own its tray lifecycle."""
    root = Path(data_root)
    root.mkdir(parents=True, exist_ok=True)
    lock = SingleInstanceLock(root / "desktop.lock")
    state_path = root / "instance.json"
    if not lock.acquire():
        existing = read_instance_state(state_path)
        if existing:
            webbrowser.open(existing.url)
            return 0
        return 2

    server = None
    state: InstanceState | None = None
    try:
        port = select_available_port()
        _configure_runtime(root, port)

        import uvicorn

        from .main import app

        server = uvicorn.Server(
            uvicorn.Config(app, host=LOOPBACK_HOST, port=port, log_level="info")
        )
        thread = threading.Thread(target=server.run, name="daily-record-ocr-server", daemon=True)
        thread.start()
        state = InstanceState(pid=os.getpid(), host=LOOPBACK_HOST, port=port)
        _wait_for_health(state.url)
        write_instance_state(state_path, state)
        webbrowser.open(state.url)
        _run_tray(state.url, server, thread)
        return 0
    finally:
        if server is not None:
            server.should_exit = True
        if state is not None:
            try:
                state_path.unlink(missing_ok=True)
            except OSError:
                pass
        lock.release()


def _configure_runtime(data_root: Path, port: int) -> None:
    os.environ["DAILY_RECORD_OCR_DATA_DIR"] = str(data_root)
    os.environ["APP_HOST"] = LOOPBACK_HOST
    os.environ["APP_PORT"] = str(port)
    os.environ["JOBS_DIR"] = str(data_root / "jobs")
    _configure_model_cache(data_root)


def _configure_model_cache(data_root: Path) -> None:
    os.environ["PADDLE_PDX_CACHE_HOME"] = str(data_root / "models" / "paddlex")


def _wait_for_health(base_url: str, timeout_seconds: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    health_url = base_url.rstrip("/") + "/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=1) as response:  # noqa: S310
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("本机服务启动超时")


def _run_tray(url: str, server: object, thread: threading.Thread) -> None:
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        thread.join()
        return

    image = Image.new("RGB", (64, 64), "#0f6fea")
    draw = ImageDraw.Draw(image)
    draw.rectangle((16, 14, 48, 50), outline="white", width=5)
    draw.line((22, 26, 42, 26), fill="white", width=4)
    draw.line((22, 36, 42, 36), fill="white", width=4)

    def open_app(*_: object) -> None:
        webbrowser.open(url)

    def open_doctor(*_: object) -> None:
        webbrowser.open(url.rstrip("/") + "/setup")

    def quit_app(icon: object, *_: object) -> None:
        server.should_exit = True
        icon.stop()

    tray = pystray.Icon(
        "DailyRecordOCR",
        image,
        "手写配方识别",
        pystray.Menu(
            pystray.MenuItem("打开应用", open_app, default=True),
            pystray.MenuItem("系统检查", open_doctor),
            pystray.MenuItem("退出", quit_app),
        ),
    )
    tray.run()
    thread.join(timeout=15)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="daily-record-ocr-lite desktop launcher")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--ocr-test", action="store_true")
    parser.add_argument("--install-models", action="store_true")
    parser.add_argument("--data-dir", type=Path, default=DATA_ROOT)
    args = parser.parse_args(argv)
    if args.self_test:
        print(json.dumps(self_test(args.data_dir), ensure_ascii=False, sort_keys=True))
        return 0
    if args.smoke_test:
        result = smoke_test(args.data_dir)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result.get("status") == "OK" else 3
    if args.ocr_test:
        result = real_ocr_test(args.data_dir)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result.get("status") == "OK" else 4
    if args.install_models:
        _configure_model_cache(args.data_dir)
        try:
            from .model_packages import install_model_packages

            result = install_model_packages(args.data_dir)
        except Exception as exc:
            result = {
                "status": "FAILED",
                "error_category": "MODEL_INSTALL_FAILED",
                "error_type": type(exc).__name__,
            }
            http_status = getattr(getattr(exc, "response", None), "status_code", None)
            if isinstance(http_status, int):
                result["http_status"] = http_status
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result.get("status") == "READY" else 5
    return run_desktop(args.data_dir)


if __name__ == "__main__":
    raise SystemExit(main())
