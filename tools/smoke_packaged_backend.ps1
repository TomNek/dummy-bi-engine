param(
    [Parameter(Mandatory = $true)]
    [string]$BackendExe,
    [string]$Workspace = "sample_project",
    [string]$ExpectedUiText = "Semantic Migration Workbench",
    [switch]$OpenCore,
    [int]$TimeoutSeconds = 90
)

$ErrorActionPreference = "Stop"
$backend = (Resolve-Path -LiteralPath $BackendExe).Path
$project = (Resolve-Path -LiteralPath $Workspace).Path
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("smw-backend-smoke-" + [guid]::NewGuid().ToString("N"))
$stdoutPath = Join-Path $tempRoot "stdout.log"
$stderrPath = Join-Path $tempRoot "stderr.log"
$process = $null
$backendName = [IO.Path]::GetFileNameWithoutExtension($backend)
$existingProcessIds = @(
    Get-Process -Name $backendName -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -eq $backend } |
        ForEach-Object { $_.Id }
)

New-Item -ItemType Directory -Path $tempRoot | Out-Null

try {
    & $backend --self-test
    if ($LASTEXITCODE -ne 0) {
        throw "Packaged backend self-test failed with exit code $LASTEXITCODE"
    }

    $token = [guid]::NewGuid().ToString("N")
    $quotedProject = '"' + $project + '"'
    $process = Start-Process `
        -FilePath $backend `
        -ArgumentList @("--port", "0", "--auth-token", $token, "--workspace", $quotedProject, "--log-level", "error") `
        -PassThru `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $port = $null
    while ((Get-Date) -lt $deadline) {
        if ($process.HasExited) {
            $stderr = if (Test-Path -LiteralPath $stderrPath) { Get-Content -LiteralPath $stderrPath -Raw } else { "" }
            throw "Packaged backend exited before readiness (code $($process.ExitCode)): $stderr"
        }
        if (Test-Path -LiteralPath $stdoutPath) {
            $portLine = Get-Content -LiteralPath $stdoutPath | Where-Object { $_ -match '^PORT=(\d+)$' } | Select-Object -Last 1
            if ($portLine) {
                $port = [int]($portLine -replace '^PORT=', '')
                break
            }
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $port) {
        throw "Packaged backend did not report a port within $TimeoutSeconds seconds"
    }

    $encodedProject = [uri]::EscapeDataString($project)
    $authHeaders = @{ "X-Desktop-Token" = $token }
    $ui = Invoke-WebRequest -Uri "http://127.0.0.1:$port/runtime/ui-react?project=$encodedProject" -Headers $authHeaders -UseBasicParsing
    if ($ui.StatusCode -ne 200 -or $ui.Content -notmatch [regex]::Escape($ExpectedUiText) -or $ui.Content -notmatch 'id="root"') {
        throw "Packaged React UI smoke failed"
    }

    $meta = Invoke-RestMethod -Uri "http://127.0.0.1:$port/runtime/meta?project=$encodedProject" -Headers $authHeaders
    if (-not $meta.ok -or -not $meta.ready -or -not $meta.version) {
        throw "Packaged metadata endpoint did not report ready/version"
    }

    $writeHeaders = @{
        "X-Desktop-Token" = $token
        "X-Requested-With" = "packaged-smoke"
    }
    if ($OpenCore) {
        $connectors = Invoke-RestMethod `
            -Uri "http://127.0.0.1:$port/runtime/data_sources/connectors" `
            -Headers $authHeaders
        if (-not $connectors.ok -or $connectors.connectors.Count -ne 17) {
            throw "Packaged open-core backend did not expose all 17 connectors"
        }
        $compiled = Invoke-RestMethod `
            -Method Post `
            -Uri "http://127.0.0.1:$port/runtime/measures/validate?project=$encodedProject" `
            -Headers $writeHeaders `
            -ContentType "application/json" `
            -Body '{"name":"Total Sales","dax":"SUM(Sales[Amount])"}'
        if (-not $compiled.ok -or -not $compiled.sql -or $null -eq $compiled.value) {
            throw "Packaged open-core compiler did not return SQL and a value"
        }
        Write-Host "[packaged-backend-smoke] PASS port=$port connectors=$($connectors.connectors.Count) compiler=ready"
    }
    else {
        $matrix = Invoke-RestMethod `
            -Method Post `
            -Uri "http://127.0.0.1:$port/runtime/visuals/v_matrix_demo/matrix?project=$encodedProject" `
            -Headers $writeHeaders `
            -ContentType "application/json" `
            -Body "{}"
        if (-not $matrix.ok -or -not $matrix.matrix -or $matrix.matrix.rowOrder.Count -lt 1 -or $matrix.matrix.values.Count -lt 1) {
            throw "Packaged matrix render did not return rows and measures"
        }
        Write-Host "[packaged-backend-smoke] PASS port=$port rows=$($matrix.matrix.rowOrder.Count) measures=$($matrix.matrix.values.Count)"
    }
}
finally {
    # A PyInstaller one-file executable can have both a bootloader parent and
    # an unpacked child. Stop every process created by this smoke for this
    # exact executable, while preserving any process that predated the run.
    Get-Process -Name $backendName -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -eq $backend -and $_.Id -notin $existingProcessIds } |
        Stop-Process -Force -ErrorAction SilentlyContinue
    if ($process) {
        $process.WaitForExit(15000) | Out-Null
    }
    if (Test-Path -LiteralPath $tempRoot) {
        $cleanupDeadline = (Get-Date).AddSeconds(15)
        do {
            try {
                Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction Stop
            }
            catch {
                if ((Get-Date) -ge $cleanupDeadline) { throw }
                Start-Sleep -Milliseconds 250
            }
        } while (Test-Path -LiteralPath $tempRoot)
    }
}
