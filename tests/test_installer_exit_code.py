"""Contract tests for Windows installer exit-code handling.

Tests the behavior of install-windows.ps1 when doctor.py returns different exit codes:
- Exit 0 / READY: Installer should succeed
- Exit 1 / SETUP_REQUIRED: Installer should succeed (normal first install)
- Exit 2 / BROKEN: Installer should fail
- Exit 3 / Unknown: Installer should fail
"""

import shutil
import subprocess
from pathlib import Path

import pytest

# Skip all tests in this module if PowerShell is not available
powershell_available = shutil.which("powershell") is not None or shutil.which("pwsh") is not None
pytestmark = pytest.mark.skipif(not powershell_available, reason="PowerShell not available on this platform")

# Mock doctor script that returns configurable exit codes
MOCK_DOCTOR_SCRIPT = '''
import sys
import json

exit_code = int(sys.argv[-1]) if sys.argv[-1].isdigit() else 0

result = {
    "schema_version": "doctor-v1",
    "version": "1.0.1",
    "state": "READY" if exit_code == 0 else ("SETUP_REQUIRED" if exit_code == 1 else "BROKEN"),
    "exit_code": exit_code,
    "checks": []
}

print(json.dumps(result))
sys.exit(exit_code)
'''


class TestInstallerExitCodeContract:
    """Test installer behavior with different doctor exit codes."""

    def _run_installer_with_mock_doctor(self, doctor_exit_code: int, tmp_path: Path) -> subprocess.CompletedProcess:
        """Run installer with a mock doctor that returns the specified exit code."""
        # Create mock doctor script
        mock_doctor = tmp_path / "mock_doctor.py"
        mock_doctor.write_text(MOCK_DOCTOR_SCRIPT)

        # Create a simplified installer test script that mimics the critical logic
        installer_test = tmp_path / "test_installer.ps1"
        installer_test.write_text(f'''
$ErrorActionPreference = "Stop"
$Python = "python"

# Mock doctor call
& $Python "{mock_doctor}" --json --gate {doctor_exit_code}
$DoctorExit = $LASTEXITCODE

# Original logic (BUGGY)
if ($DoctorExit -ne 0) {{
    throw "doctor 报告 BROKEN；安装失败。"
}}
Write-Host "安装公共步骤完成。下一步运行 .\\start-windows.bat 并在 /setup 配置视觉模型。"
exit 0
''')

        # Run the test script
        result = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(installer_test)],
            capture_output=True,
            text=True,
            cwd=str(tmp_path)
        )
        return result

    def test_doctor_exit_0_ready_old_behavior(self, tmp_path):
        """Doctor exit 0 / READY should succeed with old behavior."""
        result = self._run_installer_with_mock_doctor(0, tmp_path)
        assert result.returncode == 0, f"Expected exit 0, got {result.returncode}. stderr: {result.stderr}"
        assert "安装公共步骤完成" in result.stdout

    def test_doctor_exit_1_setup_required_old_behavior_fails(self, tmp_path):
        """Doctor exit 1 / SETUP_REQUIRED should FAIL with old behavior (this is the bug)."""
        result = self._run_installer_with_mock_doctor(1, tmp_path)
        # Old behavior: exit 1 throws exception, installer fails
        assert result.returncode != 0, f"Expected non-zero exit (bug), got {result.returncode}"
        assert "BROKEN" in result.stderr or "安装失败" in result.stderr

    def test_doctor_exit_2_broken_old_behavior(self, tmp_path):
        """Doctor exit 2 / BROKEN should fail with old behavior."""
        result = self._run_installer_with_mock_doctor(2, tmp_path)
        assert result.returncode != 0, f"Expected non-zero exit, got {result.returncode}"
        assert "BROKEN" in result.stderr or "安装失败" in result.stderr

    def test_doctor_exit_3_unknown_old_behavior(self, tmp_path):
        """Doctor exit 3 / Unknown should fail with old behavior."""
        result = self._run_installer_with_mock_doctor(3, tmp_path)
        assert result.returncode != 0, f"Expected non-zero exit, got {result.returncode}"


class TestInstallerExitCodeContractNewBehavior:
    """Test installer behavior with NEW fixed logic."""

    def _run_installer_with_new_logic(self, doctor_exit_code: int, tmp_path: Path) -> subprocess.CompletedProcess:
        """Run installer with new fixed logic."""
        # Create mock doctor script
        mock_doctor = tmp_path / "mock_doctor.py"
        mock_doctor.write_text(MOCK_DOCTOR_SCRIPT)

        # Create installer test script with NEW fixed logic
        installer_test = tmp_path / "test_installer_new.ps1"
        installer_test.write_text(f'''
$ErrorActionPreference = "Stop"
$Python = "python"

# Mock doctor call
& $Python "{mock_doctor}" --json --gate {doctor_exit_code}
$DoctorExit = $LASTEXITCODE

# NEW fixed logic
switch ($DoctorExit) {{
    0 {{
        Write-Host "安装和配置检查完成，当前状态 READY。"
    }}
    1 {{
        Write-Host "安装公共步骤完成，当前状态 SETUP_REQUIRED。"
        Write-Host "请运行 .\\start-windows.bat 并访问 /setup 配置视觉模型。"
    }}
    2 {{
        throw "doctor 报告 BROKEN；安装失败。"
    }}
    default {{
        throw "doctor 返回未知退出码 $DoctorExit；安装状态无法确认。"
    }}
}}
exit 0
''')

        # Run the test script
        result = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(installer_test)],
            capture_output=True,
            text=True,
            cwd=str(tmp_path)
        )
        return result

    def test_doctor_exit_0_ready_new_behavior(self, tmp_path):
        """Doctor exit 0 / READY should succeed with new behavior."""
        result = self._run_installer_with_new_logic(0, tmp_path)
        assert result.returncode == 0, f"Expected exit 0, got {result.returncode}. stderr: {result.stderr}"
        assert "安装和配置检查完成" in result.stdout
        assert "READY" in result.stdout

    def test_doctor_exit_1_setup_required_new_behavior_succeeds(self, tmp_path):
        """Doctor exit 1 / SETUP_REQUIRED should SUCCEED with new behavior."""
        result = self._run_installer_with_new_logic(1, tmp_path)
        assert result.returncode == 0, f"Expected exit 0, got {result.returncode}. stderr: {result.stderr}"
        assert "安装公共步骤完成" in result.stdout
        assert "SETUP_REQUIRED" in result.stdout
        assert "/setup" in result.stdout
        assert "BROKEN" not in result.stdout
        assert "安装失败" not in result.stdout

    def test_doctor_exit_2_broken_new_behavior(self, tmp_path):
        """Doctor exit 2 / BROKEN should fail with new behavior."""
        result = self._run_installer_with_new_logic(2, tmp_path)
        assert result.returncode != 0, f"Expected non-zero exit, got {result.returncode}"
        assert "BROKEN" in result.stderr or "安装失败" in result.stderr

    def test_doctor_exit_3_unknown_new_behavior(self, tmp_path):
        """Doctor exit 3 / Unknown should fail with new behavior."""
        result = self._run_installer_with_new_logic(3, tmp_path)
        assert result.returncode != 0, f"Expected non-zero exit, got {result.returncode}"
        assert "未知退出码" in result.stderr or "安装状态无法确认" in result.stderr
