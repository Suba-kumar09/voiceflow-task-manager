<#
.SYNOPSIS
  Create the backend virtual environment and install dependencies (Windows, Python 3.11).

.NOTES
  Windows Smart App Control blocks SQLAlchemy's unsigned compiled extensions and pip's
  generated .exe launchers. So this script installs SQLAlchemy in pure-Python mode, and all
  tools are run as "python -m <tool>" (never .venv\Scripts\<tool>.exe).
#>
$ErrorActionPreference = 'Stop'
$Backend = Join-Path (Split-Path -Parent $PSScriptRoot) 'backend'
$Py = Join-Path $Backend '.venv\Scripts\python.exe'

if (-not (Test-Path $Py)) {
    Write-Host 'Creating virtual environment (Python 3.11)'
    py -3.11 -m venv (Join-Path $Backend '.venv')
}

& $Py -m pip install --upgrade pip --quiet
Push-Location $Backend
try {
    & $Py -m pip install -e '.[dev]'
    if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }

    Write-Host 'Reinstalling SQLAlchemy without compiled extensions (Smart App Control)'
    $env:DISABLE_SQLALCHEMY_CEXT = '1'
    & $Py -m pip install --force-reinstall --no-deps --no-binary sqlalchemy --no-cache-dir 'sqlalchemy>=2.0.36'
    if ($LASTEXITCODE -ne 0) { throw 'SQLAlchemy reinstall failed' }
} finally {
    Remove-Item Env:DISABLE_SQLALCHEMY_CEXT -ErrorAction SilentlyContinue
    Pop-Location
}

& $Py -c "from sqlalchemy.util import has_compiled_ext; assert not has_compiled_ext(); print('Backend environment ready.')"
