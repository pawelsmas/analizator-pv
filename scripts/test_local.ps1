# Local test runner for contract tests (Windows PowerShell)
# Usage: .\scripts\test_local.ps1

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
Set-Location $ProjectRoot

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  PV Optimizer Pro - Contract Tests" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Start services
Write-Host "[1/4] Starting Docker services..." -ForegroundColor Yellow
docker-compose up -d bess-dispatch pv-calculation

# Step 2: Wait for services to be healthy
Write-Host "[2/4] Waiting for services to be ready..." -ForegroundColor Yellow

$MaxWait = 120
$Waited = 0

while ($Waited -lt $MaxWait) {
    try {
        $BessHealth = (Invoke-WebRequest -Uri "http://localhost:8031/health" -UseBasicParsing -TimeoutSec 5).StatusCode
    } catch {
        $BessHealth = 0
    }

    try {
        $PvHealth = (Invoke-WebRequest -Uri "http://localhost:8002/health" -UseBasicParsing -TimeoutSec 5).StatusCode
    } catch {
        $PvHealth = 0
    }

    if ($BessHealth -eq 200 -and $PvHealth -eq 200) {
        Write-Host "Services are ready!" -ForegroundColor Green
        break
    }

    Write-Host "  Waiting... (BESS: $BessHealth, PV: $PvHealth)"
    Start-Sleep -Seconds 5
    $Waited += 5
}

if ($Waited -ge $MaxWait) {
    Write-Host "Error: Services did not become healthy in ${MaxWait}s" -ForegroundColor Red
    docker-compose logs bess-dispatch pv-calculation
    exit 1
}

# Step 3: Run pytest
Write-Host "[3/4] Running contract tests..." -ForegroundColor Yellow
Write-Host ""

# Check if pytest is available
$PytestAvailable = Get-Command pytest -ErrorAction SilentlyContinue

if ($PytestAvailable) {
    pytest tests/contract/ -v --tb=short
    $TestResult = $LASTEXITCODE
} else {
    # Run pytest in a Python container
    Write-Host "pytest not found locally, running in Docker..."

    # Convert Windows path for Docker mount
    $TestsPath = "$ProjectRoot\tests".Replace('\', '/')

    docker run --rm `
        --network host `
        -v "${TestsPath}:/tests" `
        python:3.11-slim `
        bash -c "pip install pytest requests && pytest /tests/contract/ -v --tb=short"

    $TestResult = $LASTEXITCODE
}

# Step 4: Report results
Write-Host ""
Write-Host "=========================================="

if ($TestResult -eq 0) {
    Write-Host "  All contract tests PASSED" -ForegroundColor Green
} else {
    Write-Host "  Some tests FAILED" -ForegroundColor Red
}

Write-Host "=========================================="

exit $TestResult
