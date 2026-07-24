param(
    [ValidateSet("Cpu", "Gpu")]
    [string]$OcrMode = "Cpu",
    [string]$PaddleInstallCommand = "",
    [switch]$SkipOcr
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$OriginalLocation = Get-Location
$ShortDrive = $null

foreach ($code in 90..80) {
    $candidate = "$([char]$code):"
    if (-not (Test-Path "$candidate\")) {
        $ShortDrive = $candidate
        break
    }
}
if (-not $ShortDrive) {
    throw "没有可用的临时盘符；无法安全解压 Paddle 的深层 wheel 路径。"
}

subst.exe $ShortDrive $Root
if ($LASTEXITCODE -ne 0) {
    throw "无法把项目映射到临时短盘符 $ShortDrive。"
}

try {
    $InstallRoot = "$ShortDrive\"
    $Python = Join-Path $InstallRoot ".venv\Scripts\python.exe"
    Set-Location $InstallRoot

    python -c "import sys; assert (3, 11) <= sys.version_info[:2] <= (3, 12), '需要 Python 3.11 或 3.12'"
    if ($LASTEXITCODE -ne 0) { throw "Python 版本检查失败。" }
    if (-not (Test-Path $Python)) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw "创建 .venv 失败。" }
    }
    & $Python -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "升级 pip 失败。" }
    & $Python -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "安装核心依赖失败。" }

    if ($SkipOcr) {
        Write-Warning "已跳过 OCR；此安装只能进入 SETUP_REQUIRED 或显式 Demo，不能声称真实识别就绪。"
    } elseif ($OcrMode -eq "Gpu") {
        if (-not $PaddleInstallCommand) {
            throw "GPU 安装必须按 PaddlePaddle 官方兼容矩阵传入 -PaddleInstallCommand。"
        }
        $OldPath = $env:PATH
        $OldVirtualEnv = $env:VIRTUAL_ENV
        try {
            $env:VIRTUAL_ENV = (Join-Path $InstallRoot ".venv")
            $env:PATH = "$(Split-Path $Python);$OldPath"
            & ([scriptblock]::Create($PaddleInstallCommand))
            if ($LASTEXITCODE -ne 0) {
                throw "Paddle 安装命令失败，退出码 $LASTEXITCODE。"
            }
        } finally {
            $env:PATH = $OldPath
            $env:VIRTUAL_ENV = $OldVirtualEnv
        }
        & $Python -m pip install "paddleocr>=3.0,<4" "opencv-python-headless>=4.9,<5"
        if ($LASTEXITCODE -ne 0) { throw "安装 PaddleOCR/OpenCV 失败。" }
    } else {
        & $Python -m pip install -r requirements-ocr.txt
        if ($LASTEXITCODE -ne 0) { throw "安装 CPU OCR 依赖失败。" }
    }

    if (-not $SkipOcr) {
        & $Python -c "import cv2, paddle, paddleocr; paddle.utils.run_check(); print('PaddleOCR', paddleocr.__version__, 'OpenCV', cv2.__version__)"
        if ($LASTEXITCODE -ne 0) { throw "Paddle/PaddleOCR/OpenCV 运行检查失败。" }
    }
    New-Item -ItemType Directory -Force -Path "data\jobs", "data\cache\ocr", "data\cache\vision", "data\models" | Out-Null
    & $Python -c "from lite_app.settings import SettingsService; from pathlib import Path; s=SettingsService(Path('data')); s.save(s.load())"
    if ($LASTEXITCODE -ne 0) { throw "创建默认设置失败。" }
    & $Python scripts\doctor.py --json --gate
    $DoctorExit = $LASTEXITCODE
    if ($DoctorExit -ne 0) {
        throw "doctor 报告 BROKEN；安装失败。"
    }
    Write-Host "安装公共步骤完成。下一步运行 .\start-windows.bat 并在 /setup 配置视觉模型。"
} finally {
    Set-Location $OriginalLocation
    subst.exe $ShortDrive /D
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "临时盘符 $ShortDrive 清理失败；请运行 subst $ShortDrive /D。"
    }
}
