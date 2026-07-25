param(
    [int]$BackendPort = 8001,
    [int]$FrontendPort = 5173
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RuntimeDir = Join-Path $ProjectRoot ".tmp"
$StateFile = Join-Path $RuntimeDir "dev-processes.json"
New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null

function Test-Listening([int]$Port) {
    return $null -ne (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Wait-Http([string]$Url, [int]$Seconds = 90) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    $lastResponse = $null
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-RestMethod -Uri $Url -TimeoutSec 3
            $lastResponse = $response
            if (
                $response.ok -eq $true -and
                $response.ready -eq $true -and
                $response.status -eq "healthy"
            ) {
                return $response
            }
        } catch {}
        Start-Sleep -Milliseconds 750
    }
    $detail = if ($lastResponse) {
        $lastResponse | ConvertTo-Json -Compress -Depth 4
    } else {
        "no HTTP response"
    }
    throw "Timed out waiting for a healthy backend at $Url. Last probe: $detail. See .tmp/dev-backend.err.log."
}

$started = @{}
$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Missing .venv. Create it and install requirements.txt first."
}

if (-not (Test-Listening $BackendPort)) {
    $backend = Start-Process -FilePath $python `
        -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$BackendPort") `
        -WorkingDirectory $ProjectRoot `
        -RedirectStandardOutput (Join-Path $RuntimeDir "dev-backend.out.log") `
        -RedirectStandardError (Join-Path $RuntimeDir "dev-backend.err.log") `
        -WindowStyle Hidden -PassThru
    $started.backend = @{
        pid = $backend.Id
        started_at = $backend.StartTime.ToUniversalTime().ToString("o")
    }
}

$health = Wait-Http "http://127.0.0.1:$BackendPort/health?deep=true"

if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot "frontend\node_modules"))) {
    throw "Missing frontend/node_modules. Run npm --prefix frontend install first."
}
if (-not (Test-Listening $FrontendPort)) {
    $npm = (Get-Command npm.cmd -ErrorAction Stop).Source
    $frontend = Start-Process -FilePath $npm `
        -ArgumentList @("--prefix", "frontend", "run", "dev", "--", "--host", "127.0.0.1", "--port", "$FrontendPort") `
        -WorkingDirectory $ProjectRoot `
        -RedirectStandardOutput (Join-Path $RuntimeDir "dev-frontend.out.log") `
        -RedirectStandardError (Join-Path $RuntimeDir "dev-frontend.err.log") `
        -WindowStyle Hidden -PassThru
    $started.frontend = @{
        pid = $frontend.Id
        started_at = $frontend.StartTime.ToUniversalTime().ToString("o")
    }
}

$started | ConvertTo-Json | Set-Content -LiteralPath $StateFile -Encoding utf8
Write-Output "Backend: http://127.0.0.1:$BackendPort (ready=$($health.ready), queue=$($health.services.collection_queue))"
Write-Output "Frontend: http://127.0.0.1:$FrontendPort"
Write-Output "Process state: $StateFile"
