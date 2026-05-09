param(
    [string]$ServiceName = "RemChannelBot",
    [string]$NssmPath = "nssm.exe"
)

$ErrorActionPreference = "Stop"
$NssmCommand = Get-Command $NssmPath -ErrorAction SilentlyContinue
if (-not $NssmCommand) {
    throw "NSSM was not found. Install NSSM and pass -NssmPath, or put nssm.exe on PATH."
}

if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {
    Stop-Service -Name $ServiceName -ErrorAction SilentlyContinue
    & $NssmCommand.Source remove $ServiceName confirm
}

Write-Host "Uninstalled $ServiceName."
