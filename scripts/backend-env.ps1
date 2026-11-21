<#
.SYNOPSIS
  Prepare this terminal for running the VoiceFlow backend, worker or tests on this laptop.
.DESCRIPTION
  Windows Smart App Control blocks psycopg's bundled (unsigned) database library. This makes
  psycopg use PostgreSQL's own libpq.dll (D:\tools\pgsql\bin) through its pure-Python mode
  instead. Same driver, same behaviour; no Windows security setting is changed.
  Use it by "dot-sourcing" (note the leading dot):
.EXAMPLE
  . .\scripts\backend-env.ps1
#>
param([string]$PgBin = 'D:\tools\pgsql\bin', [string]$HfHome = 'D:\ai-cache\hf')
if (-not (Test-Path (Join-Path $PgBin 'libpq.dll'))) { throw "libpq.dll not found in $PgBin" }
if (($env:PATH -split ';') -notcontains $PgBin) { $env:PATH = "$PgBin;$env:PATH" }
$env:PSYCOPG_IMPL = 'python'
$env:HF_HOME = $HfHome
Write-Host "Backend environment ready (database library: $PgBin\libpq.dll, models: $HfHome)"
