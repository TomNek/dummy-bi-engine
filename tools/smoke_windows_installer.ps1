param(
    [Parameter(Mandatory = $true)]
    [string]$Installer,
    [string]$Workspace = "sample_project",
    [string]$ExpectedUiText = "Dummy BI Engine",
    [string]$AppExecutableName = "dummy-bi-engine.exe",
    [switch]$OpenCore,
    [int]$TimeoutSeconds = 120
)

$ErrorActionPreference = "Stop"
$installerPath = (Resolve-Path -LiteralPath $Installer).Path
$projectPath = (Resolve-Path -LiteralPath $Workspace).Path
$installRoot = Join-Path ([IO.Path]::GetTempPath()) ("smw-installed-smoke-" + [guid]::NewGuid().ToString("N"))
$logRoot = Join-Path ([IO.Path]::GetTempPath()) ("smw-desktop-smoke-" + [guid]::NewGuid().ToString("N"))
$appPath = Join-Path $installRoot $AppExecutableName
$backendPath = Join-Path $installRoot "dax_backend.exe"
$uninstallerPath = Join-Path $installRoot "uninstall.exe"
$appStdoutPath = Join-Path $logRoot "desktop-stdout.log"
$appStderrPath = Join-Path $logRoot "desktop-stderr.log"
$appProcess = $null

New-Item -ItemType Directory -Path $logRoot | Out-Null

try {
    $install = Start-Process -FilePath $installerPath -ArgumentList @("/S", "/D=$installRoot") -PassThru -Wait -WindowStyle Hidden
    if ($install.ExitCode -ne 0) {
        throw "Silent installer failed with exit code $($install.ExitCode)"
    }
    foreach ($required in @($appPath, $backendPath, $uninstallerPath)) {
        if (-not (Test-Path -LiteralPath $required)) {
            throw "Installed file missing: $required"
        }
    }

    $backendSmoke = @{
        BackendExe = $backendPath
        Workspace = $projectPath
        ExpectedUiText = $ExpectedUiText
        TimeoutSeconds = $TimeoutSeconds
    }
    if ($OpenCore) { $backendSmoke.OpenCore = $true }
    & (Join-Path $PSScriptRoot "smoke_packaged_backend.ps1") @backendSmoke

    $quotedProject = '"' + $projectPath + '"'
    $appProcess = Start-Process `
        -FilePath $appPath `
        -ArgumentList @("--workspace", $quotedProject) `
        -PassThru `
        -WindowStyle Hidden `
        -RedirectStandardOutput $appStdoutPath `
        -RedirectStandardError $appStderrPath
    $deadline = (Get-Date).AddSeconds([Math]::Min($TimeoutSeconds, 30))
    while ((Get-Date) -lt $deadline -and -not $appProcess.HasExited) {
        Start-Sleep -Milliseconds 250
        if (((Get-Date) - $appProcess.StartTime).TotalSeconds -ge 5) { break }
    }
    if ($appProcess.HasExited) {
        $desktopError = if (Test-Path -LiteralPath $appStderrPath) { Get-Content -LiteralPath $appStderrPath -Raw } else { "" }
        $desktopOutput = if (Test-Path -LiteralPath $appStdoutPath) { Get-Content -LiteralPath $appStdoutPath -Raw } else { "" }
        throw "Installed desktop application exited during launch smoke (code $($appProcess.ExitCode)). stdout=$desktopOutput stderr=$desktopError"
    }
    Write-Host "[installer-smoke] desktop launch remained responsive"
}
finally {
    if ($appProcess) {
        Get-Process -Name ([IO.Path]::GetFileNameWithoutExtension($appPath)) -ErrorAction SilentlyContinue |
            Where-Object { $_.Path -eq $appPath } |
            Stop-Process -Force -ErrorAction SilentlyContinue
        $appProcess.WaitForExit(15000) | Out-Null
    }
    # The desktop shell owns a separately packaged backend sidecar. Stop only
    # the sidecar from this isolated installation before asking NSIS to remove
    # its files.
    Get-Process -Name ([IO.Path]::GetFileNameWithoutExtension($backendPath)) -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -eq $backendPath } |
        Stop-Process -Force -ErrorAction SilentlyContinue
    $sidecarDeadline = (Get-Date).AddSeconds(15)
    while (
        (Get-Process -Name ([IO.Path]::GetFileNameWithoutExtension($backendPath)) -ErrorAction SilentlyContinue |
            Where-Object { $_.Path -eq $backendPath }) -and
        (Get-Date) -lt $sidecarDeadline
    ) {
        Start-Sleep -Milliseconds 250
    }
    if (Test-Path -LiteralPath $logRoot) {
        Remove-Item -LiteralPath $logRoot -Recurse -Force
    }
    if (Test-Path -LiteralPath $uninstallerPath) {
        $uninstall = Start-Process -FilePath $uninstallerPath -ArgumentList @("/S") -PassThru -Wait -WindowStyle Hidden
        if ($uninstall.ExitCode -ne 0) {
            throw "Silent uninstaller failed with exit code $($uninstall.ExitCode)"
        }
    }
    $cleanupDeadline = (Get-Date).AddSeconds(20)
    while ((Test-Path -LiteralPath $installRoot) -and (Get-Date) -lt $cleanupDeadline) {
        Start-Sleep -Milliseconds 250
    }
    if (Test-Path -LiteralPath $installRoot) {
        throw "Uninstaller did not remove the isolated install directory: $installRoot"
    }
}

Write-Host "[installer-smoke] PASS"
