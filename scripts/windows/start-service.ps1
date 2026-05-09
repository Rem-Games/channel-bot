param(
    [string]$ServiceName = "RemChannelBot"
)

$ErrorActionPreference = "Stop"
Start-Service -Name $ServiceName
Get-Service -Name $ServiceName
