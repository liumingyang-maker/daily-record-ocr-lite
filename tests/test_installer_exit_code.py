"""Contract tests for Windows installer exit-code handling.

Tests the shared doctor-exit-contract.ps1 module that defines how installers
and CI workflows interpret Doctor exit codes.

Exit code semantics:
- 0: READY - all checks passed
- 1: SETUP_REQUIRED - installation succeeded but Vision needs configuration
- 2: BROKEN - critical check failed
- Other: UNKNOWN - unexpected state
"""

import shutil
import subprocess
from pathlib import Path

import pytest

# Check if PowerShell is available
POWERSHELL_AVAILABLE = shutil.which("powershell") is not None or shutil.which("pwsh") is not None


def get_powershell_cmd():
    """Get the PowerShell command for the current platform."""
    if shutil.which("powershell"):
        return "powershell"
    elif shutil.which("pwsh"):
        return "pwsh"
    return None


# Path to the shared contract file
CONTRACT_FILE = Path(__file__).resolve().parent.parent / "install" / "doctor-exit-contract.ps1"


@pytest.mark.skipif(not POWERSHELL_AVAILABLE, reason="PowerShell not available on this platform")
class TestDoctorExitContract:
    """Test the shared doctor-exit-contract.ps1 module directly."""

    def _call_contract(self, exit_code: int) -> dict:
        """Call Resolve-DoctorExitCode with the given exit code and return the result."""
        ps_cmd = get_powershell_cmd()
        if not ps_cmd:
            pytest.skip("PowerShell not available")

        # Create a test script that loads the contract and calls it
        test_script = f'''
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
. "{CONTRACT_FILE}"
$result = Resolve-DoctorExitCode -DoctorExit {exit_code}
Write-Output ($result | ConvertTo-Json -Compress)
'''
        
        # Write temp script with UTF-8 BOM
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.ps1', delete=False, encoding='utf-8-sig') as f:
            f.write(test_script)
            temp_script = f.name
        
        try:
            result = subprocess.run(
                [ps_cmd, "-ExecutionPolicy", "Bypass", "-File", temp_script],
                capture_output=True,
                encoding='utf-8',
                errors='replace'
            )
            if result.returncode != 0:
                pytest.fail(f"PowerShell script failed: {result.stderr}")
            import json
            return json.loads(result.stdout.strip())
        finally:
            Path(temp_script).unlink(missing_ok=True)

    def test_doctor_exit_0_ready(self):
        """Doctor exit 0 should return Success=true, State=READY."""
        result = self._call_contract(0)
        assert result["Success"] is True
        assert result["State"] == "READY"

    def test_doctor_exit_1_setup_required(self):
        """Doctor exit 1 should return Success=true, State=SETUP_REQUIRED."""
        result = self._call_contract(1)
        assert result["Success"] is True
        assert result["State"] == "SETUP_REQUIRED"

    def test_doctor_exit_2_broken(self):
        """Doctor exit 2 should return Success=false, State=BROKEN."""
        result = self._call_contract(2)
        assert result["Success"] is False
        assert result["State"] == "BROKEN"

    def test_doctor_exit_3_unknown(self):
        """Doctor exit 3 should return Success=false, State=UNKNOWN."""
        result = self._call_contract(3)
        assert result["Success"] is False
        assert result["State"] == "UNKNOWN"

    def test_doctor_exit_negative(self):
        """Doctor exit -1 should return Success=false."""
        result = self._call_contract(-1)
        assert result["Success"] is False

    def test_doctor_exit_255(self):
        """Doctor exit 255 should return Success=false."""
        result = self._call_contract(255)
        assert result["Success"] is False


@pytest.mark.skipif(not POWERSHELL_AVAILABLE, reason="PowerShell not available on this platform")
class TestInstallerUsesContract:
    """Test that the actual installer uses the shared contract correctly."""

    def test_installer_loads_contract(self, tmp_path):
        """Verify that install-windows.ps1 dot-sources doctor-exit-contract.ps1."""
        ps_cmd = get_powershell_cmd()
        if not ps_cmd:
            pytest.skip("PowerShell not available")

        # Read the installer file with UTF-8 encoding
        installer = Path(__file__).resolve().parent.parent / "install" / "install-windows.ps1"
        content = installer.read_text(encoding='utf-8')
        
        # Verify it loads the contract
        assert "doctor-exit-contract.ps1" in content
        assert "Resolve-DoctorExitCode" in content
