param(
    [switch]$PurgeData,
    [switch]$RemoveProject
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Venv = Join-Path $Root ".venv"
if (Test-Path $Venv) {
    Remove-Item -LiteralPath $Venv -Recurse -Force
}
if ($PurgeData) {
    $Data = (Join-Path $Root "data")
    if ((Resolve-Path $Data -ErrorAction SilentlyContinue).Path.StartsWith($Root)) {
        Remove-Item -LiteralPath $Data -Recurse -Force
    }
} else {
    Write-Host "data 已保留。只有显式 -PurgeData 才会删除识别数据。"
}
if ($RemoveProject) {
    Write-Warning "请退出当前目录后由用户或安装 AI 删除项目目录：$Root"
}
Write-Host "本地虚拟环境已卸载。"
