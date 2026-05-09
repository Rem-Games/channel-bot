param(
    [string]$ServiceName = "RemChannelBot"
)

$ErrorActionPreference = "Stop"
$ProjectDir = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$LogPath = Join-Path $ProjectDir "data\service.stderr.log"

try {
    Start-Service -Name $ServiceName
    Get-Service -Name $ServiceName
}
catch {
    if (Test-Path $LogPath) {
        Write-Host "Recent service stderr log:"
        Get-Content $LogPath -Tail 80
    }
    throw
}
