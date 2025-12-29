#
# Gate PR Checks - Fail if any GitHub check is not SUCCESS
#
# Usage:
#   .\scripts\gate_pr_checks.ps1 -PRNumber <number>
#   .\scripts\gate_pr_checks.ps1 -PRNumber <number> -Repo "owner/repo"
#
# Exit codes:
#   0 - All checks passed (SUCCESS)
#   1 - Some checks failed or are pending
#   2 - Invalid arguments or gh CLI error
#
# Example n8n integration:
#   Execute this script before merge/tag/release steps
#   If exit code != 0, stop the workflow
#

param(
    [Parameter(Mandatory=$true)]
    [int]$PRNumber,

    [Parameter(Mandatory=$false)]
    [string]$Repo = ""
)

$ErrorActionPreference = "Stop"

Write-Host "Checking PR #$PRNumber status..."

# Build repo flag if provided
$repoArg = @()
if ($Repo) {
    $repoArg = @("--repo", $Repo)
}

try {
    $statusJson = gh pr view $PRNumber @repoArg --json statusCheckRollup 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Failed to get PR status"
        Write-Host $statusJson
        exit 2
    }
} catch {
    Write-Host "ERROR: gh CLI failed: $_"
    exit 2
}

$status = $statusJson | ConvertFrom-Json

$totalCount = $status.statusCheckRollup.Count
$failedChecks = $status.statusCheckRollup | Where-Object { $_.conclusion -ne "SUCCESS" -and $null -ne $_.conclusion }
$pendingChecks = $status.statusCheckRollup | Where-Object { $null -eq $_.conclusion }

$failedCount = ($failedChecks | Measure-Object).Count
$pendingCount = ($pendingChecks | Measure-Object).Count
$passedCount = $totalCount - $failedCount - $pendingCount

Write-Host "Total checks: $totalCount"
Write-Host "Passed: $passedCount"
Write-Host "Pending: $pendingCount"
Write-Host "Failed: $failedCount"

if ($pendingCount -gt 0) {
    Write-Host ""
    Write-Host "GATE BLOCKED: $pendingCount checks still pending"
    Write-Host "Pending checks:"
    foreach ($check in $pendingChecks) {
        $name = if ($check.name) { $check.name } else { $check.context }
        Write-Host "  - $name"
    }
    exit 1
}

if ($failedCount -gt 0) {
    Write-Host ""
    Write-Host "GATE BLOCKED: $failedCount checks failed"
    Write-Host "Failed checks:"
    foreach ($check in $failedChecks) {
        $name = if ($check.name) { $check.name } else { $check.context }
        Write-Host "  - $name : $($check.conclusion)"
    }
    exit 1
}

Write-Host ""
Write-Host "GATE PASSED: All $totalCount checks succeeded"
exit 0
