import json
import socket
from pathlib import Path

import httpx
import pytest


def test_desktop_host_must_be_loopback():
    from lite_app.desktop_launcher import validate_loopback_host

    assert validate_loopback_host("127.0.0.1") == "127.0.0.1"
    with pytest.raises(ValueError):
        validate_loopback_host("0.0.0.0")


def test_port_selection_skips_an_occupied_port():
    from lite_app.desktop_launcher import select_available_port

    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied.bind(("127.0.0.1", 0))
    occupied.listen(1)
    used_port = int(occupied.getsockname()[1])
    try:
        selected = select_available_port(preferred=used_port, attempts=10)
    finally:
        occupied.close()

    assert selected != used_port
    assert selected > 0


def test_single_instance_lock_rejects_second_owner(tmp_path: Path):
    from lite_app.desktop_launcher import SingleInstanceLock

    first = SingleInstanceLock(tmp_path / "desktop.lock")
    second = SingleInstanceLock(tmp_path / "desktop.lock")

    assert first.acquire() is True
    try:
        assert second.acquire() is False
    finally:
        second.release()
        first.release()


def test_single_instance_lock_can_be_reacquired_after_clean_exit(tmp_path: Path):
    from lite_app.desktop_launcher import SingleInstanceLock

    path = tmp_path / "desktop.lock"
    first = SingleInstanceLock(path)
    assert first.acquire() is True
    first.release()

    restarted = SingleInstanceLock(path)
    assert restarted.acquire() is True
    restarted.release()


def test_instance_state_contains_only_connection_metadata(tmp_path: Path):
    from lite_app.desktop_launcher import InstanceState, read_instance_state, write_instance_state

    path = tmp_path / "instance.json"
    state = InstanceState(pid=123, host="127.0.0.1", port=8876)

    write_instance_state(path, state)

    assert read_instance_state(path) == state
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == {"host": "127.0.0.1", "pid": 123, "port": 8876}
    assert "key" not in path.read_text(encoding="utf-8").lower()


def test_invalid_or_non_loopback_instance_state_is_ignored(tmp_path: Path):
    from lite_app.desktop_launcher import read_instance_state

    path = tmp_path / "instance.json"
    path.write_text('{"pid":1,"host":"0.0.0.0","port":8765}', encoding="utf-8")

    assert read_instance_state(path) is None


def test_self_test_checks_lock_port_and_data_directory(tmp_path: Path):
    from lite_app.desktop_launcher import self_test

    result = self_test(tmp_path / "desktop-data")

    assert result["status"] == "OK"
    assert result["loopback_only"] is True
    assert result["single_instance"] is True
    assert result["data_directory_writable"] is True


def test_smoke_test_cli_returns_failure_status(monkeypatch, tmp_path: Path):
    import lite_app.desktop_launcher as launcher

    monkeypatch.setattr(launcher, "smoke_test", lambda _path: {"status": "FAILED"})

    assert launcher.main(["--smoke-test", "--data-dir", str(tmp_path)]) == 3


def test_real_ocr_cli_requires_real_tokens(monkeypatch, tmp_path: Path):
    import lite_app.desktop_launcher as launcher

    monkeypatch.setattr(launcher, "real_ocr_test", lambda _path: {"status": "FAILED"})

    assert launcher.main(["--ocr-test", "--data-dir", str(tmp_path)]) == 4


def test_model_install_cli_requires_verified_ready_state(monkeypatch, tmp_path: Path):
    import lite_app.desktop_launcher as launcher
    import lite_app.model_packages as model_packages

    monkeypatch.setattr(
        model_packages,
        "install_model_packages",
        lambda _path: {"status": "DOWNLOAD_REQUIRED"},
    )

    assert launcher.main(["--install-models", "--data-dir", str(tmp_path)]) == 5


def test_model_install_cli_reports_only_safe_exception_type(
    monkeypatch, tmp_path: Path, capsys
):
    import lite_app.desktop_launcher as launcher
    import lite_app.model_packages as model_packages

    def fail_install(_path):
        raise FileNotFoundError("private local path must not be printed")

    monkeypatch.setattr(model_packages, "install_model_packages", fail_install)

    assert launcher.main(["--install-models", "--data-dir", str(tmp_path)]) == 5
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "error_category": "MODEL_INSTALL_FAILED",
        "error_type": "FileNotFoundError",
        "status": "FAILED",
    }


def test_model_install_cli_reports_http_status_without_response_body(
    monkeypatch, tmp_path: Path, capsys
):
    import lite_app.desktop_launcher as launcher
    import lite_app.model_packages as model_packages

    request = httpx.Request("GET", "https://models.example.invalid/archive.tar")
    response = httpx.Response(302, request=request, text="private upstream response")

    def fail_install(_path):
        raise httpx.HTTPStatusError("private message", request=request, response=response)

    monkeypatch.setattr(model_packages, "install_model_packages", fail_install)

    assert launcher.main(["--install-models", "--data-dir", str(tmp_path)]) == 5
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "error_category": "MODEL_INSTALL_FAILED",
        "error_type": "HTTPStatusError",
        "http_status": 302,
        "status": "FAILED",
    }


def test_local_diagnostics_redact_api_keys(monkeypatch):
    import lite_app.desktop_launcher as launcher

    monkeypatch.setenv("DESKTOP_DIAGNOSTICS", "1")
    fake_key = "sk-" + "ws-private-value"
    failure = launcher._ocr_failure("LOAD", RuntimeError(f"failed with {fake_key}"))

    assert failure["diagnostic_preview"] == "failed with <API_KEY>"
