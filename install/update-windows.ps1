param(
    [string]$Ref = "latest",
    [ValidateSet("Cpu", "Gpu")]
    [string]$OcrMode = "Cpu",
    [string]$PaddleInstallCommand = "",
    [switch]$SkipOcr
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
$PreviousCommit = (git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "无法读取当前 Git commit。"
}
$PreviousLabel = (git describe --tags --exact-match 2>$null)
if (-not $PreviousLabel) {
    $PreviousLabel = $PreviousCommit
}
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
if ($LASTEXITCODE -ne 0) {
    throw "无法从 origin 获取版本标签。"
}

$TargetRef = $Ref
if ($Ref -eq "latest") {
    $TargetRef = git tag --list "v[0-9]*" --sort=-v:refname |
        Where-Object { $_ -match '^v\d+\.\d+\.\d+$' } |
        Select-Object -First 1
    if (-not $TargetRef) {
        throw "没有找到稳定 Release Tag（格式 v主版本.次版本.修订版本）。"
    }
}

$TargetCommit = (git rev-list -n 1 $TargetRef 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $TargetCommit) {
    throw "无法解析更新目标: $TargetRef"
}
$TargetCommit = $TargetCommit.Trim()
if ($PreviousCommit -eq $TargetCommit) {
    Write-Host "已经是目标稳定版本 $TargetRef；无需重复安装。"
    Write-Host "数据备份位于 $Backup"
    exit 0
}

git show-ref --verify --quiet "refs/tags/$TargetRef"
$IsTag = $LASTEXITCODE -eq 0
if ($IsTag) {
    git checkout --detach $TargetRef
} else {
    git checkout $TargetRef
    if ($LASTEXITCODE -ne 0) {
        throw "无法切换到更新目标: $TargetRef"
    }
    git pull --ff-only origin $TargetRef
}
if ($LASTEXITCODE -ne 0) {
    throw "无法更新到目标: $TargetRef"
}

$Installer = Join-Path $Root "install\install-windows.ps1"
$InstallArguments = @{ OcrMode = $OcrMode }
if ($PaddleInstallCommand) {
    $InstallArguments["PaddleInstallCommand"] = $PaddleInstallCommand
}
if ($SkipOcr) {
    $InstallArguments["SkipOcr"] = $true
}
& $Installer @InstallArguments
Write-Host "更新完成：$PreviousLabel -> $TargetRef"
Write-Host "回滚点：$PreviousCommit"
Write-Host "数据备份位于 $Backup"
