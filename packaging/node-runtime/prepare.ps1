<#
.SYNOPSIS
  Thin Windows wrapper around packaging/node-runtime/prepare.py
#>
[CmdletBinding()]
param(
    [switch]$NoStage
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $RepoRoot
$Py = $null
$cmd = Get-Command python -ErrorAction SilentlyContinue
if ($cmd) { $Py = $cmd.Source }
if (-not $Py) { $Py = Join-Path $RepoRoot ".venv\Scripts\python.exe" }
$argsList = @(Join-Path $PSScriptRoot "prepare.py")
if ($NoStage) { $argsList += "--no-stage" }
& $Py @argsList
if ($LASTEXITCODE -ne 0) { throw "prepare.py failed" }
