<#
.SYNOPSIS
  Start, stop or check VoiceFlow's local development PostgreSQL (D:\tools\pgdata, port 5433).
.EXAMPLE
  .\scripts\dev-db.ps1 start
#>
param(
    [Parameter(Mandatory)][ValidateSet('start', 'stop', 'status')][string]$Action,
    [string]$PgBin = 'D:\tools\pgsql\bin',
    [string]$DataDir = 'D:\tools\pgdata',
    [int]$Port = 5433
)

$pgctl = Join-Path $PgBin 'pg_ctl.exe'
switch ($Action) {
    'start' {
        & $pgctl status -D $DataDir *> $null
        if ($LASTEXITCODE -eq 0) { Write-Host 'Already running.'; break }
        # Own hidden console (survives this terminal closing); wait only for pg_ctl itself.
        $logFile = Join-Path $DataDir 'server.log'
        $p = Start-Process -FilePath $pgctl -WindowStyle Hidden -PassThru -ArgumentList @(
            'start', '-D', "`"$DataDir`"", '-w', '-l', "`"$logFile`"",
            '-o', "`"-p $Port -c listen_addresses=localhost`"")
        $p.WaitForExit()
        if ($p.ExitCode -ne 0) { Write-Error "Start failed; see $logFile"; exit 1 }
        Write-Host "Started on localhost:$Port"
    }
    'stop' { & $pgctl stop -D $DataDir -m fast }
    'status' { & $pgctl status -D $DataDir }
}
