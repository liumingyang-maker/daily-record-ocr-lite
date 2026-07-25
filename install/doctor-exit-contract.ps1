<#
.SYNOPSIS
    Shared contract for interpreting Doctor exit codes.
.DESCRIPTION
    This module provides a single source of truth for how installers and CI
    workflows interpret the exit code from `scripts/doctor.py --json --gate`.
    
    Exit code semantics:
    - 0: READY - all checks passed
    - 1: SETUP_REQUIRED - installation succeeded but Vision needs configuration
    - 2: BROKEN - critical check failed
    - Other: UNKNOWN - unexpected state
#>

function Resolve-DoctorExitCode {
    <#
    .SYNOPSIS
        Interprets a Doctor exit code and returns a structured result.
    .PARAMETER DoctorExit
        The exit code from doctor.py --json --gate
    .OUTPUTS
        Hashtable with Success (bool), State (string), Message (string)
    #>
    param([int]$DoctorExit)

    switch ($DoctorExit) {
        0 {
            return @{
                Success = $true
                State = "READY"
                Message = "Installation check complete. Status: READY."
            }
        }
        1 {
            return @{
                Success = $true
                State = "SETUP_REQUIRED"
                Message = "Installation complete. Status: SETUP_REQUIRED. Please visit /setup to configure Vision."
            }
        }
        2 {
            return @{
                Success = $false
                State = "BROKEN"
                Message = "Doctor reported BROKEN. Installation failed."
            }
        }
        default {
            return @{
                Success = $false
                State = "UNKNOWN"
                Message = "Doctor returned unexpected exit code $DoctorExit. Installation status unknown."
            }
        }
    }
}
