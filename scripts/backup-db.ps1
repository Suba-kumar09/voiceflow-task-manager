<#
.SYNOPSIS
  Back up the VoiceFlow database to a compressed dump file, keeping the newest N backups.
.DESCRIPTION
  Uses pg_dump's custom format (compressed; restore with scripts\restore-db.ps1).
  The admin password is read from a file outside the repository and passed to pg_dump
  through the PGPASSWORD environment variable for this process only (never logged).
.EXAMPLE
  .\scripts\backup-db.ps1
  .\scripts\backup-db.ps1 -Keep 30
#>
param(
    [string]$Database = 'voiceflow',
    [string]$OutDir = 'D:\voiceflow-backups',
    [int]$Keep = 14,
    [string]$PgBin = 'D:\tools\pgsql\bin',
    [int]$Port = 5433,
    [string]$AdminUser = 'postgres',
    [string]$PasswordFile = 'D:\tools\postgres-dev-admin-password.txt'
)
$ErrorActionPreference = 'Stop'

New-Item -ItemType Directory -Force $OutDir | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$file = Join-Path $OutDir "$Database-$stamp.dump"

$env:PGPASSWORD = (Get-Content $PasswordFile -Raw).Trim()
try {
    & (Join-Path $PgBin 'pg_dump.exe') -h localhost -p $Port -U $AdminUser -d $Database -Fc -f $file
    if ($LASTEXITCODE -ne 0) { throw "pg_dump failed (exit $LASTEXITCODE)" }
    # Prove the file is readable: list its contents (fails on a truncated/corrupt dump).
    $entries = (& (Join-Path $PgBin 'pg_restore.exe') --list $file | Measure-Object -Line).Lines
    if ($LASTEXITCODE -ne 0 -or $entries -lt 10) { throw "Backup file looks incomplete: $file" }
}
finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
}

$size = [math]::Round((Get-Item $file).Length / 1KB, 1)
Write-Host "Backup written: $file ($size KB, $entries entries)"

# Retention: keep the newest $Keep backups of this database.
$old = Get-ChildItem $OutDir -Filter "$Database-*.dump" | Sort-Object Name -Descending | Select-Object -Skip $Keep
foreach ($f in $old) { Remove-Item $f.FullName; Write-Host "Removed old backup: $($f.Name)" }
