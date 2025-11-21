@echo off
REM PV Optimizer - Build Script for Windows
REM Builds all Docker images for the microservices

echo ==========================================
echo PV Optimizer - Building Docker Images
echo ==========================================

REM Build Data Analysis Service
echo.
echo Building Data Analysis Service...
docker build -t pv-optimizer/data-analysis:latest ./services/data-analysis/
if %errorlevel% neq 0 exit /b %errorlevel%
echo [OK] Data Analysis Service built

REM Build PV Calculation Service
echo.
echo Building PV Calculation Service...
docker build -t pv-optimizer/pv-calculation:latest ./services/pv-calculation/
if %errorlevel% neq 0 exit /b %errorlevel%
echo [OK] PV Calculation Service built

REM Build Economics Service
echo.
echo Building Economics Service...
docker build -t pv-optimizer/economics:latest ./services/economics/
if %errorlevel% neq 0 exit /b %errorlevel%
echo [OK] Economics Service built

REM Build Frontend Service
echo.
echo Building Frontend Service...
docker build -t pv-optimizer/frontend:latest ./services/frontend/
if %errorlevel% neq 0 exit /b %errorlevel%
echo [OK] Frontend Service built

echo.
echo ==========================================
echo All images built successfully!
echo ==========================================

REM List images
echo.
echo Docker images:
docker images | findstr pv-optimizer

pause
