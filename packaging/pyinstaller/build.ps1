<#
.SYNOPSIS
  Thin Windows wrapper around packaging/pyinstaller/build.py
#>
[CmdletBinding()]
param(
    [string]$Python = "",
    [switch]$SkipSmoke,
    [switch]$NoStage
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $RepoRoot

if (-not $Python) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $Python = $cmd.Source } else { $Python = (Join-Path $RepoRoot ".venv\Scripts\python.exe") }
}
if (-not (Test-Path $Python)) { throw "Python not found: $Python" }

$argsList = @((Join-Path $PSScriptRoot "build.py"), "--python", $Python)
if ($SkipSmoke) { $argsList += "--skip-smoke" }
if ($NoStage) { $argsList += "--no-stage" }

Write-Host "[pyinstaller] Delegating to build.py with $Python"
& $Python @argsList
if ($LASTEXITCODE -ne 0) { throw "build.py failed with exit code $LASTEXITCODE" }
