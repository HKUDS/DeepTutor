<#
.SYNOPSIS
  Prepare packaging/node-runtime/win-x64 from the cached official Node zip.

.DESCRIPTION
  Extracts node-runtime-bundle/node-v22.23.2-win-x64.zip into win-x64/ so
  electron-builder can ship node.exe next to DeepTutor.exe.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot ".")
$Zip = Join-Path $Root "node-runtime-bundle\node-v22.23.2-win-x64.zip"
$Out = Join-Path $Root "win-x64"
$Exe = Join-Path $Out "node.exe"

if (Test-Path $Exe) {
    Write-Host "[node-runtime] Already prepared: $Exe"
    & $Exe --version
    exit 0
}

if (-not (Test-Path $Zip)) {
    throw "Missing $Zip — download Node 22 win-x64 zip into node-runtime-bundle/ first."
}

$Staging = Join-Path $Root "_extract_tmp"
if (Test-Path $Staging) { Remove-Item $Staging -Recurse -Force }
if (Test-Path $Out) { Remove-Item $Out -Recurse -Force }
New-Item -ItemType Directory -Force -Path $Staging | Out-Null

Write-Host "[node-runtime] Extracting $Zip ..."
Expand-Archive -Path $Zip -DestinationPath $Staging -Force

$Nested = Get-ChildItem $Staging -Directory | Select-Object -First 1
if (-not $Nested) { throw "Zip did not contain a Node directory" }
Move-Item $Nested.FullName $Out
Remove-Item $Staging -Recurse -Force

if (-not (Test-Path $Exe)) { throw "node.exe missing after extract: $Exe" }
Write-Host "[node-runtime] Ready: $Exe"
& $Exe --version
