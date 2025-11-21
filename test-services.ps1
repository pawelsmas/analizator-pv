# Test if backend services are running
Write-Host "Testing PV Optimizer Microservices..." -ForegroundColor Cyan

$services = @{
    "Data Analysis" = "http://localhost:8001/health"
    "PV Calculation" = "http://localhost:8002/health"
    "Economics" = "http://localhost:8003/health"
    "Advanced Analytics" = "http://localhost:8004/health"
    "Typical Days" = "http://localhost:8005/health"
}

foreach ($service in $services.GetEnumerator()) {
    try {
        $response = Invoke-WebRequest -Uri $service.Value -TimeoutSec 2 -UseBasicParsing
        if ($response.StatusCode -eq 200) {
            Write-Host "[OK] $($service.Key) - Running" -ForegroundColor Green
        } else {
            Write-Host "[WARN] $($service.Key) - Status: $($response.StatusCode)" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "[ERROR] $($service.Key) - Not responding" -ForegroundColor Red
    }
}

Write-Host "`nTo start services, run:" -ForegroundColor Cyan
Write-Host "docker-compose up -d" -ForegroundColor White
