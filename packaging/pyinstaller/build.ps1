<#
.SYNOPSIS
  Build the Windows x64 DeepTutor backend with PyInstaller (onedir).

.DESCRIPTION
  Prefer the active interpreter on PATH, then a repo .venv. The
  packaging/python-runtime tree is only used when PyInstaller already
  imports there (uv-managed trees are often EXTERNALLY-MANAGED and lack a
  root python.exe that PyInstaller expects).

  Output: dist/pyinstaller/win-x64/deeptutor/deeptutor.exe
#>
[CmdletBinding()]
param(
    [string]$Python = "",
    [switch]$SkipSmoke
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $RepoRoot

function Test-PyImport {
    param([string]$Interpreter, [string]$Module)
    & $Interpreter -c "import $Module" 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Test-PyInstallerReady {
    param([string]$Interpreter)
    # PyInstaller probes sys.executable / venv home; "import sys" alone is not enough.
    return (Test-PyImport -Interpreter $Interpreter -Module "PyInstaller")
}

function Test-WritableEnv {
    param([string]$Interpreter)
    $prefix = & $Interpreter -c "import sys; print(sys.prefix)" 2>$null
    if (-not $prefix) { return $false }
    $marker = Join-Path $prefix.Trim() "Lib\EXTERNALLY-MANAGED"
    if (Test-Path $marker) { return $false }
    $marker2 = Join-Path $prefix.Trim() "EXTERNALLY-MANAGED"
    if (Test-Path $marker2) { return $false }
    return $true
}

function Resolve-BuildPython {
    param([string]$Preferred)
    if ($Preferred) {
        if (-not (Test-Path $Preferred)) {
            throw "Python not found: $Preferred"
        }
        return (Resolve-Path $Preferred).Path
    }

    $candidates = [System.Collections.Generic.List[string]]::new()

    # Active environment first (e.g. `conda activate deeptutor` / venv).
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) {
        $candidates.Add($cmd.Source)
    }

    foreach ($c in @(
        (Join-Path $RepoRoot ".venv\Scripts\python.exe"),
        (Join-Path $RepoRoot "..\.venv\Scripts\python.exe"),
        (Join-Path $RepoRoot "packaging\python-runtime\win-x64\Scripts\python.exe"),
        (Join-Path $RepoRoot "packaging\python-runtime\win-x64\python.exe")
    )) {
        if (Test-Path $c) { $candidates.Add((Resolve-Path $c).Path) }
    }

    $seen = @{}
    foreach ($c in $candidates) {
        if ($seen.ContainsKey($c)) { continue }
        $seen[$c] = $true
        try {
            & $c -c "import sys; print(sys.version)" 2>$null | Out-Null
            if ($LASTEXITCODE -ne 0) { continue }
        } catch { continue }

        if (Test-PyInstallerReady -Interpreter $c) {
            return $c
        }
        # Skip uv/externally-managed trees that cannot install PyInstaller via pip.
        if (-not (Test-WritableEnv -Interpreter $c)) {
            Write-Host "[pyinstaller] Skipping externally-managed Python: $c"
            continue
        }
        return $c
    }
    throw "No usable Python interpreter found. Activate a writable venv or pass -Python path\to\python.exe"
}

function Install-WithUvOrPip {
    param(
        [string]$Interpreter,
        [string[]]$PipArgs
    )
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($uv) {
        Write-Host "[pyinstaller] uv pip install --python $Interpreter $($PipArgs -join ' ')"
        & uv pip install --python $Interpreter @PipArgs
        if ($LASTEXITCODE -eq 0) { return }
        Write-Host "[pyinstaller] uv pip failed (exit $LASTEXITCODE); trying pip..."
    }
    & $Interpreter -m pip install @PipArgs
    if ($LASTEXITCODE -eq 0) { return }
    # Last resort for odd managed trees the user explicitly passed via -Python.
    & $Interpreter -m pip install --break-system-packages @PipArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install: $($PipArgs -join ' ')"
    }
}

$Py = Resolve-BuildPython -Preferred $Python
Write-Host "[pyinstaller] Using Python: $Py"

if (-not (Test-PyInstallerReady -Interpreter $Py)) {
    Write-Host "[pyinstaller] Ensuring PyInstaller is installed..."
    Install-WithUvOrPip -Interpreter $Py -PipArgs @("pyinstaller>=6.0,<7")
    if (-not (Test-PyInstallerReady -Interpreter $Py)) {
        throw "PyInstaller still not importable from $Py"
    }
} else {
    Write-Host "[pyinstaller] PyInstaller already available"
}

Write-Host "[pyinstaller] Ensuring DeepTutor is importable..."
if (-not (Test-PyImport -Interpreter $Py -Module "deeptutor")) {
    Write-Host "[pyinstaller] Installing DeepTutor editable..."
    Install-WithUvOrPip -Interpreter $Py -PipArgs @("-e", ".")
}
& $Py -c "import deeptutor, deeptutor_cli; print(deeptutor.__file__)"
if ($LASTEXITCODE -ne 0) { throw "deeptutor is not importable from $Py" }

$OutRoot = Join-Path $RepoRoot "dist\pyinstaller\win-x64"
$WorkPath = Join-Path $OutRoot "build"
$DistPath = $OutRoot
$Spec = Join-Path $PSScriptRoot "deeptutor.spec"

New-Item -ItemType Directory -Force -Path $OutRoot | Out-Null

Write-Host "[pyinstaller] Building onedir from $Spec ..."
& $Py -m PyInstaller `
    --noconfirm `
    --clean `
    --distpath $DistPath `
    --workpath $WorkPath `
    $Spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

$Exe = Join-Path $DistPath "deeptutor\deeptutor.exe"
if (-not (Test-Path $Exe)) {
    throw "Expected output missing: $Exe"
}

Write-Host "[pyinstaller] Built: $Exe"

if (-not $SkipSmoke) {
    Write-Host "[pyinstaller] Smoke: --help"
    & $Exe --help
    if ($LASTEXITCODE -ne 0) { throw "deeptutor.exe --help failed" }
    Write-Host "[pyinstaller] Smoke: serve --help"
    & $Exe serve --help
    if ($LASTEXITCODE -ne 0) { throw "deeptutor.exe serve --help failed" }
    Write-Host "[pyinstaller] Smoke: start --help"
    & $Exe start --help
    if ($LASTEXITCODE -ne 0) { throw "deeptutor.exe start --help failed" }
}

Write-Host "[pyinstaller] Done."
