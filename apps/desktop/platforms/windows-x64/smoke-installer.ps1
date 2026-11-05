# Run the actual installed Electron app with a fresh, non-ASCII user path.
$ErrorActionPreference = 'Stop'
$desktop = (Resolve-Path "$PSScriptRoot/../..").Path
$installer = @(Get-ChildItem "$desktop/out/*-Setup.exe")
if ($installer.Count -ne 1) { throw 'Expected exactly one Windows installer' }
$root = Join-Path $env:TEMP "DeepTutor 安装 smoke $([guid]::NewGuid())"
$install = Join-Path $root 'installed app'
$userRoot = Join-Path $root 'user data'
New-Item -ItemType Directory -Path $install, $userRoot -Force | Out-Null
# A custom destination may already contain unrelated files of the same types.
$sentinel = Join-Path $install 'keep-user-file.dll'
Set-Content $sentinel 'unrelated user file'
$oldPath = $env:PATH
$oldHome = $env:OPEN_DEEPTUTOR_TEST_HOME
$appProcess = $null
$log = Join-Path $userRoot 'logs/runtime.log'
try {
    Write-Host 'Installing into a path containing spaces and Chinese characters...'
    $setup = Start-Process $installer[0].FullName -ArgumentList @('/S', "/D=$install") -Wait -PassThru
    if ($setup.ExitCode -ne 0) { throw "Installer exited with $($setup.ExitCode)" }
    $exe = Join-Path $install 'Open DeepTutor.exe'
    if (!(Test-Path $exe) -or !(Test-Path $sentinel)) { throw 'Install did not preserve the destination' }
    $env:OPEN_DEEPTUTOR_TEST_HOME = $userRoot
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot;$env:SystemRoot\System32\Wbem"
    Write-Host 'Starting the installed app with no developer tools on PATH...'
    $appProcess = Start-Process $exe -PassThru
    $deadline = (Get-Date).AddMinutes(10)
    $backend = $null
    $frontend = $null
    do {
        if ($appProcess.HasExited) { throw "App exited early: $($appProcess.ExitCode)" }
        if (Test-Path $log) {
            $text = Get-Content $log -Raw
            if ($text -match 'UnicodeEncodeError|Desktop startup failed:') { throw "Installed app failed to start:`n$text" }
            if ($text -match 'Uvicorn running on (http://127\.0\.0\.1:\d+)') { $backend = $Matches[1] }
            if ($text -match 'Local:\s+(http://127\.0\.0\.1:\d+)') { $frontend = $Matches[1] }
        }
        if ($backend -and $frontend) {
            try {
                $health = Invoke-WebRequest "$backend/health/ready" -TimeoutSec 5
                $page = Invoke-WebRequest $frontend -TimeoutSec 5
                $proxy = Invoke-WebRequest "$frontend/api/settings/ui" -TimeoutSec 5
                if ($health.StatusCode -eq 200 -and $page.Content -match 'DeepTutor' -and $proxy.StatusCode -eq 200) { break }
            } catch { }
        }
        if ((Get-Date) -gt $deadline) { throw "Installed app did not become ready. Runtime log:`n$text" }
        Start-Sleep -Seconds 2
    } while ($true)

    # Closing the real window must stop both services, not just Electron.
    Write-Host 'UI and API are ready. Checking window close and uninstall...'
    $appProcess.Refresh()
    if (!$appProcess.CloseMainWindow()) { throw 'App did not expose a main window' }
    if (!$appProcess.WaitForExit(30000)) { throw 'App did not quit after closing its window' }
    foreach ($url in @($frontend, "$backend/health/ready")) {
        $responded = $false
        try { Invoke-WebRequest $url -TimeoutSec 3 | Out-Null; $responded = $true } catch { }
        if ($responded) { throw "Service survived app exit: $url" }
    }
    $data = Join-Path $userRoot 'workspace/data/user/settings/interface.json'
    if (!(Test-Path $data)) { throw 'App did not initialize its user data' }
    Start-Process (Join-Path $install 'Uninstall Open DeepTutor.exe') -ArgumentList '/S' -Wait | Out-Null
    $deadline = (Get-Date).AddSeconds(30)
    while ((Test-Path $exe) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 1 }
    if (Test-Path $exe) { throw 'Uninstall left the app executable behind' }
    if (!(Test-Path $sentinel) -or !(Test-Path $data)) { throw 'Uninstall removed user files or learning data' }
    Write-Host 'PASS: Windows install, first launch, UI/API, window close, and uninstall preserve user data.'
} finally {
    if ($appProcess -and !$appProcess.HasExited) {
        & "$env:SystemRoot/System32/taskkill.exe" /PID $appProcess.Id /T /F | Out-Null
    }
    $env:PATH = $oldPath
    $env:OPEN_DEEPTUTOR_TEST_HOME = $oldHome
    if (Test-Path $log) { Copy-Item $log "$desktop/.local/windows-x64/installed-app.log" -Force }
}
