<#
.SYNOPSIS
  Restore a VoiceFlow backup into a database.
.DESCRIPTION
  By default restores into a SEPARATE database (voiceflow_restore_check) so a backup can be
  tested without touching live data. Restoring over the live 'voiceflow' database requires
  -Force; stop the backend and the reminders worker first.
  Objects are created as the application user (read from backend\.env), so the app can use
  the restored database directly.
.EXAMPLE
  .\scripts\restore-db.ps1 -File D:\voiceflow-backups\voiceflow-20261121-101500.dump
  .\scripts\restore-db.ps1 -File <dump> -Target voiceflow -Force
#>
param(
    [Parameter(Mandatory)][string]$File,
    [string]$Target = 'voiceflow_restore_check',
    [switch]$Force,
    [string]$PgBin = 'D:\tools\pgsql\bin',
    [int]$Port = 5433,
    [string]$AdminUser = 'postgres',
    [string]$PasswordFile = 'D:\tools\postgres-dev-admin-password.txt',
    [string]$EnvFile = (Join-Path $PSScriptRoot '..\backend\.env')
)
$ErrorActionPreference = 'Stop'

if (-not (Test-Path $File)) { throw "Backup file not found: $File" }
if ($Target -eq 'voiceflow' -and -not $Force) {
    throw "Refusing to overwrite the live 'voiceflow' database without -Force. Stop the backend and worker first."
}
if ($Target -notmatch '^[a-z_][a-z0-9_]*$') { throw "Invalid database name: $Target" }

# Application role = user part of VOICEFLOW_DATABASE_URL (the password is not read).
$appUser = (Select-String -Path $EnvFile -Pattern '^VOICEFLOW_DATABASE_URL=\S+://([^:@/]+)[:@]').Matches[0].Groups[1].Value
if (-not $appUser) { throw "Could not read the application user from $EnvFile" }

$psql = Join-Path $PgBin 'psql.exe'
$env:PGPASSWORD = (Get-Content $PasswordFile -Raw).Trim()
try {
    $common = @('-h', 'localhost', '-p', $Port, '-U', $AdminUser)
    & $psql @common -d postgres -v ON_ERROR_STOP=1 -q -c "DROP DATABASE IF EXISTS $Target WITH (FORCE);" -c "CREATE DATABASE $Target OWNER $appUser;"
    if ($LASTEXITCODE -ne 0) { throw 'Could not recreate the target database.' }
    & (Join-Path $PgBin 'pg_restore.exe') @common -d $Target --no-owner --role=$appUser --exit-on-error $File
    if ($LASTEXITCODE -ne 0) { throw "pg_restore failed (exit $LASTEXITCODE)" }
    $summary = & $psql @common -d $Target -At -c "SELECT (SELECT version_num FROM alembic_version) || ' | ' || (SELECT count(*) FROM users) || ' users | ' || (SELECT count(*) FROM tasks) || ' tasks | ' || (SELECT count(*) FROM audit_events) || ' audit events'"
}
finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
}
Write-Host "Restored into '$Target': migration $summary"
