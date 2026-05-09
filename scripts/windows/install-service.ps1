param(
    [string]$ServiceName = "RemChannelBot",
    [string]$DisplayName = "Rem Channel Bot",
    [string]$NssmPath = "nssm.exe"
)

$ErrorActionPreference = "Stop"
$ProjectDir = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$ProjectDir = $ProjectDir.Path
$PythonPath = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$EnvPath = Join-Path $ProjectDir ".env"
$DataDir = Join-Path $ProjectDir "data"

if (-not (Test-Path $PythonPath)) {
    throw "Missing $PythonPath. Create the virtual environment and install requirements first."
}

if (-not (Test-Path $EnvPath)) {
    throw "Missing $EnvPath. Create it from .env.example before starting the service."
}

$NssmCommand = Get-Command $NssmPath -ErrorAction SilentlyContinue
if (-not $NssmCommand) {
    throw "NSSM was not found. Install NSSM and pass -NssmPath, or put nssm.exe on PATH."
}

New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

& $NssmCommand.Source install $ServiceName $PythonPath "-m remchannelbot"
& $NssmCommand.Source set $ServiceName DisplayName $DisplayName
& $NssmCommand.Source set $ServiceName AppDirectory $ProjectDir
& $NssmCommand.Source set $ServiceName AppStdout (Join-Path $DataDir "service.stdout.log")
& $NssmCommand.Source set $ServiceName AppStderr (Join-Path $DataDir "service.stderr.log")
& $NssmCommand.Source set $ServiceName AppRotateFiles 1
& $NssmCommand.Source set $ServiceName AppRotateBytes 1048576
& $NssmCommand.Source set $ServiceName AppEnvironmentExtra "PYTHONUNBUFFERED=1"
& $NssmCommand.Source set $ServiceName Start SERVICE_AUTO_START

Write-Host "Installed $ServiceName."
Write-Host "Start it with: .\scripts\windows\start-service.ps1"
