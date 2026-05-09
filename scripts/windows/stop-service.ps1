param(
    [string]$ServiceName = "RemChannelBot"
)

$ErrorActionPreference = "Stop"
Stop-Service -Name $ServiceName
Get-Service -Name $ServiceName
