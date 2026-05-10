param(
    [switch]$VoiceText,
    [string]$CondaEnv = "rk3588-ai",
    [string]$CondaRoot = "D:\anaconda3",
    [string]$LlmModel = "qwen-turbo",
    [string]$DashScopeApiKey = $env:DASHSCOPE_API_KEY
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $ProjectRoot

if (-not $DashScopeApiKey) {
    $SecureKey = Read-Host "请输入 DASHSCOPE_API_KEY" -AsSecureString
    $DashScopeApiKey = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureKey)
    )
}

$env:DASHSCOPE_API_KEY = $DashScopeApiKey
$env:LLM_MODEL = $LlmModel
$env:LLM_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# Keep Python/C/UI/voice on the same vision socket path.
# On RK3588 Linux the default /tmp path is fine; override here only if needed.
if (-not $env:VISION_SOCKET_PATH) {
    $env:VISION_SOCKET_PATH = "/tmp/vision_inspection.sock"
}

$CondaBat = Join-Path $CondaRoot "condabin\conda.bat"
if (-not (Test-Path $CondaBat)) {
    throw "找不到 conda.bat：$CondaBat。请检查 CondaRoot 参数。"
}

$RunArgs = @("scripts/run_device.py")
if ($VoiceText) {
    $RunArgs += "--voice-text"
}

Write-Host "========================================="
Write-Host "启动视觉 + 语音 + LLM 联动"
Write-Host "项目目录: $ProjectRoot"
Write-Host "Conda环境: $CondaEnv"
Write-Host "LLM模型:   $env:LLM_MODEL"
Write-Host "Socket:    $env:VISION_SOCKET_PATH"
Write-Host "文字模式:  $VoiceText"
Write-Host "========================================="

& $CondaBat run -n $CondaEnv python @RunArgs
