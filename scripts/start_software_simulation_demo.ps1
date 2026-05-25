param(
    [string]$PythonExe = "D:\anaconda3\envs\rk3588-ai\python.exe",
    [double]$Interval = 2.0,
    [int]$ScenarioTicks = 4,
    [int]$CameraIndex = 0,
    [double]$VideoFps = 15.0,
    [switch]$KeepLogs,
    [switch]$NoCamera,
    [switch]$NoUi,
    [switch]$NoVoice
)

# 软件仿真版一键演示脚本。
#
# 这个脚本会打开几个独立窗口：
#   1. 仿真后端窗口；
#   2. PyQt UI 窗口；
#   3. 语音文本模式窗口。
#
# 之所以分窗口，是为了让你能看清楚每个模块在做什么：
# 仿真后端负责造数据和接电脑摄像头，UI 负责显示数据，语音模块负责发送查询命令。

$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $ProjectRoot

if (-not (Test-Path $PythonExe)) {
    $PythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($PythonCmd) {
        $PythonExe = $PythonCmd.Source
    } else {
        throw "找不到 Python。请检查 PythonExe 参数，或者把 python 加入 PATH。"
    }
}

# 让所有 Python 模块使用同一个 socket 路径。
# 当前 Windows 环境下如果 Unix socket 不可用，服务端会自动回退到 TCP 127.0.0.1:8765。
# 这里仍然设置环境变量，是为了和以后 RK3588 Linux 部署方式保持一致。
$SocketPath = Join-Path $ProjectRoot ".tmp\vision_inspection.sock"
$env:VISION_SOCKET_PATH = $SocketPath

function Start-DemoWindow {
    param(
        [string]$Title,
        [string]$Command
    )

    $WindowCommand = @(
        "`$Host.UI.RawUI.WindowTitle = '$Title'",
        "Set-Location '$ProjectRoot'",
        "`$env:VISION_SOCKET_PATH = '$SocketPath'",
        $Command,
        "Write-Host",
        "Read-Host '按回车关闭这个窗口'"
    ) -join [Environment]::NewLine

    Start-Process powershell -ArgumentList @(
        "-NoExit",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        $WindowCommand
    )
}

$ResetArg = ""
if (-not $KeepLogs) {
    $ResetArg = "--reset"
}

$CameraArg = "--camera --camera-index $CameraIndex"
if ($NoCamera) {
    $CameraArg = ""
}

Write-Host "========================================="
Write-Host "启动软件仿真演示"
Write-Host "项目目录: $ProjectRoot"
Write-Host "Python:   $PythonExe"
Write-Host "Socket:   $SocketPath"
Write-Host "Camera:   $(-not $NoCamera)"
Write-Host "VideoFps: $VideoFps"
Write-Host "UI:       $(-not $NoUi)"
Write-Host "Voice:    $(-not $NoVoice)"
Write-Host "========================================="

Start-DemoWindow `
    -Title "RK3588 软件仿真后端" `
    -Command "& `"$PythonExe`" scripts/run_software_simulation.py $ResetArg $CameraArg --video-fps $VideoFps --interval $Interval --scenario-ticks $ScenarioTicks"

Start-Sleep -Seconds 2

if (-not $NoUi) {
    Start-DemoWindow `
        -Title "RK3588 仿真 UI" `
        -Command "& `"$PythonExe`" ui/main_window.py"
}

if (-not $NoVoice) {
    Start-DemoWindow `
        -Title "RK3588 语音文本模式" `
        -Command "& `"$PythonExe`" voice/voice_loop.py --text"
}

Write-Host "已发起启动。请到新窗口里看日志和输入语音文本命令。"
