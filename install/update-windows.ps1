param(
    [string]$Ref = "master",
    [ValidateSet("Cpu", "Gpu")]
    [string]$OcrMode = "Cpu",
    [string]$PaddleInstallCommand = "",
    [switch]$SkipOcr
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
if (git status --porcelain) {
    throw "工作区有未提交改动；为避免覆盖，更新已停止。"
}
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Backup = Join-Path $Root "backups\data-$Stamp"
if (Test-Path "data") {
    New-Item -ItemType Directory -Force -Path $Backup | Out-Null
    Copy-Item -Recurse -Force -Path "data\*" -Destination $Backup
}
git fetch --tags origin
git checkout $Ref
git pull --ff-only origin $Ref

$Installer = Join-Path $Root "install\install-windows.ps1"
$InstallArguments = @{ OcrMode = $OcrMode }
if ($PaddleInstallCommand) {
    $InstallArguments["PaddleInstallCommand"] = $PaddleInstallCommand
}
if ($SkipOcr) {
    $InstallArguments["SkipOcr"] = $true
}
& $Installer @InstallArguments
Write-Host "更新完成；数据备份位于 $Backup"
