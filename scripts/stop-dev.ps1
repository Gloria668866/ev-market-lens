$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$StateFile = Join-Path $ProjectRoot ".tmp\dev-processes.json"

if (-not (Test-Path -LiteralPath $StateFile)) {
    Write-Output "No process state file found; nothing was stopped."
    exit 0
}

$state = Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json

function Stop-VerifiedProcessTree([int]$TargetProcessId, [datetime]$ExpectedStart) {
    $root = Get-Process -Id $TargetProcessId -ErrorAction SilentlyContinue
    if (-not $root) { return $false }

    $actualStart = $root.StartTime.ToUniversalTime()
    if ([math]::Abs(($actualStart - $ExpectedStart.ToUniversalTime()).TotalSeconds) -gt 2) {
        Write-Warning "Skipped PID $TargetProcessId because it was reused by another process."
        return $false
    }

    function Get-DescendantIds([int]$ParentId) {
        $children = Get-CimInstance Win32_Process |
            Where-Object { $_.ParentProcessId -eq $ParentId }
        $ids = @()
        foreach ($child in $children) {
            $ids += Get-DescendantIds ([int]$child.ProcessId)
            $ids += [int]$child.ProcessId
        }
        return $ids
    }

    foreach ($childId in (Get-DescendantIds $TargetProcessId)) {
        Stop-Process -Id $childId -ErrorAction SilentlyContinue
    }
    Stop-Process -Id $TargetProcessId -ErrorAction SilentlyContinue
    return $true
}

foreach ($name in @("frontend", "backend")) {
    $entry = $state.$name
    if (-not $entry) { continue }
    if ($entry -isnot [PSCustomObject] -or -not $entry.pid -or -not $entry.started_at) {
        Write-Warning "Skipped legacy or invalid $name state entry; no process was stopped."
        continue
    }
    $targetProcessId = [int]$entry.pid
    $expectedStart = [datetime]::Parse(
        [string]$entry.started_at,
        [System.Globalization.CultureInfo]::InvariantCulture,
        [System.Globalization.DateTimeStyles]::RoundtripKind
    )
    if (Stop-VerifiedProcessTree $targetProcessId $expectedStart) {
        Write-Output "Stopped $name process tree (root PID $targetProcessId)"
    }
}

Remove-Item -LiteralPath $StateFile
