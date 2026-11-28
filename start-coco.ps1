# Start DeepTutor-CoCo locally (backend :8001 + frontend :3782).
# Uses the conda env "deeptutor" and Node 22 for this process only,
# so the global nvm default (Node 24) stays untouched.

$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot
$envRoot = "C:\Users\Peter\miniconda3\envs\deeptutor"
$node22 = "C:\nvm\v22.20.0"
# ffmpeg/ffprobe: duration + cover frame for uploaded videos (optional).
$ffmpeg = "C:\Users\Peter\tools\ffmpeg"

foreach ($p in @("$envRoot\python.exe", "$node22\node.exe")) {
    if (-not (Test-Path $p)) { throw "Missing required runtime: $p" }
}

$env:PATH = "$node22;$envRoot;$envRoot\Scripts;$env:PATH"
if (Test-Path "$ffmpeg\ffprobe.exe") { $env:PATH = "$ffmpeg;$env:PATH" }
$env:DEEPTUTOR_HOME = $repo
$env:PYTHONIOENCODING = "utf-8"

Set-Location $repo
& "$envRoot\Scripts\deeptutor.exe" start @args
