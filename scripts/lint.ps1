# Lint script for PV Optimizer (Windows PowerShell)
# Usage: .\scripts\lint.ps1 [-Fix]

param(
    [switch]$Fix
)

$ErrorActionPreference = "Continue"

if ($Fix) {
    Write-Host "🔧 Running in FIX mode..." -ForegroundColor Green
} else {
    Write-Host "🔍 Running in CHECK mode (use -Fix to auto-fix)..." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "📦 Python Linting (ruff)" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

$ruffPath = Get-Command ruff -ErrorAction SilentlyContinue
if ($ruffPath) {
    if ($Fix) {
        ruff check services/ --fix
        ruff format services/
    } else {
        ruff check services/
        ruff format services/ --check
    }
} else {
    Write-Host "⚠️  ruff not installed. Install with: pip install ruff" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "🌐 JavaScript Linting (ESLint)" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

$npxPath = Get-Command npx -ErrorAction SilentlyContinue
if ($npxPath) {
    if ($Fix) {
        npx eslint "services/frontend-*/**/*.js" --fix
    } else {
        npx eslint "services/frontend-*/**/*.js"
    }
} else {
    Write-Host "⚠️  npx not found. Install Node.js first." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "✨ JavaScript Formatting (Prettier)" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

if ($npxPath) {
    if ($Fix) {
        npx prettier --write "services/frontend-*/**/*.js" "services/frontend-*/**/*.css" "services/frontend-*/**/*.html"
    } else {
        npx prettier --check "services/frontend-*/**/*.js" "services/frontend-*/**/*.css" "services/frontend-*/**/*.html"
    }
} else {
    Write-Host "⚠️  npx not found. Install Node.js first." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "✅ Linting complete!" -ForegroundColor Green
