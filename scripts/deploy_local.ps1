<#
.SYNOPSIS
    Safe local Docker Compose deployment and health verification script.
.DESCRIPTION
    Deploys or updates the AI DevOps Multi-Agent stack locally using Docker Compose:
    1. Optionally pulls a published GHCR image (if -Pull is specified) or builds locally.
    2. Validates docker-compose.yml configuration.
    3. Starts/restarts calculator-app, prometheus, grafana, and frontend while preserving all named volumes.
    4. Verifies container health, /health, /agents (6 specialist mappings), /metrics, /admin/version,
       Prometheus scrape target readiness (up == 1), Grafana health, and Frontend availability on 127.0.0.1:4173.
    Never deletes volumes or user data. Never enables automatic remediation.
#>
param(
    [string]$AppImage = "",
    [switch]$Pull,
    [switch]$SkipBuild,
    [int]$TimeoutSeconds = 90
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $RepoRoot

try {
    if ($AppImage) {
        $env:APP_IMAGE = $AppImage
    }
    if (-not $env:DEVOPS_LLM_ENABLED) {
        $env:DEVOPS_LLM_ENABLED = "false"
    }

    Write-Host "==> [1/7] Validating Docker Compose configuration..." -ForegroundColor Cyan
    docker compose config --quiet
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose configuration validation failed."
    }

    if ($Pull -and $env:APP_IMAGE) {
        Write-Host "==> [2/7] Pulling published image $($env:APP_IMAGE)..." -ForegroundColor Cyan
        docker pull $env:APP_IMAGE
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to pull image $($env:APP_IMAGE)."
        }
        if (-not $SkipBuild) {
            docker compose build frontend
            if ($LASTEXITCODE -ne 0) {
                throw "Frontend Docker image build failed."
            }
        }
    } elseif (-not $SkipBuild) {
        Write-Host "==> [2/7] Building local application and frontend Docker images..." -ForegroundColor Cyan
        docker compose build calculator-app frontend
        if ($LASTEXITCODE -ne 0) {
            throw "Docker image build failed."
        }
    } else {
        Write-Host "==> [2/7] Skipping image build/pull as requested." -ForegroundColor Cyan
    }

    Write-Host "==> [3/7] Starting Docker Compose stack (preserving named volumes)..." -ForegroundColor Cyan
    docker compose up -d
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose up -d failed."
    }

    Write-Host "==> [4/7] Verifying backend /health and /admin/version..." -ForegroundColor Cyan
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $healthOk = $false
    while ((Get-Date) -lt $deadline) {
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:8100/health" -TimeoutSec 3
            if ($health.status -eq "ok") {
                $healthOk = $true
                Write-Host "    /health OK (version: $($health.version))" -ForegroundColor Green
                break
            }
        } catch {
            Start-Sleep -Seconds 2
        }
    }
    if (-not $healthOk) {
        throw "Application /health did not become ready within $TimeoutSeconds seconds."
    }

    $ver = Invoke-RestMethod -Uri "http://127.0.0.1:8100/admin/version" -TimeoutSec 3
    Write-Host "    /admin/version OK (version: $($ver.version), history entries: $($ver.history.Count))" -ForegroundColor Green

    Write-Host "==> [5/7] Verifying /agents (six specialist model assignments)..." -ForegroundColor Cyan
    $agentsResp = Invoke-RestMethod -Uri "http://127.0.0.1:8100/agents" -TimeoutSec 3
    if ($agentsResp.agents.Count -ne 6) {
        throw "Expected 6 specialist agents, got $($agentsResp.agents.Count)."
    }
    Write-Host "    /agents OK (enabled: $($agentsResp.enabled), count: $($agentsResp.agents.Count))" -ForegroundColor Green

    Write-Host "==> [6/7] Verifying /metrics and Prometheus scrape target (up == 1)..." -ForegroundColor Cyan
    $metricsResp = Invoke-WebRequest -Uri "http://127.0.0.1:8100/metrics" -UseBasicParsing -TimeoutSec 3
    if ($metricsResp.Content -notmatch "calc_requests_total") {
        throw "/metrics did not expose calc_requests_total."
    }
    Write-Host "    /metrics OK" -ForegroundColor Green

    $promHealthy = Invoke-WebRequest -Uri "http://127.0.0.1:9090/-/healthy" -UseBasicParsing -TimeoutSec 3
    if ($promHealthy.StatusCode -ne 200) {
        throw "Prometheus /-/healthy returned $($promHealthy.StatusCode)."
    }

    $scrapeDeadline = (Get-Date).AddSeconds(30)
    $upVal = $null
    while ((Get-Date) -lt $scrapeDeadline) {
        $upQuery = Invoke-RestMethod -Uri 'http://127.0.0.1:9090/api/v1/query?query=up{job="calculator-app"}' -TimeoutSec 5
        if ($upQuery.status -eq "success" -and $upQuery.data.result.Count -gt 0) {
            $upVal = [string]$upQuery.data.result[0].value[1]
            if ($upVal -eq "1") {
                break
            }
        }
        Start-Sleep -Seconds 2
    }
    if ($upVal -ne "1") {
        throw "Prometheus scrape validation failed for up{job=`"calculator-app`"}: expected '1', got '$upVal'."
    }
    Write-Host "    Prometheus healthy & target scrape verified (up=$upVal)" -ForegroundColor Green

    Write-Host "==> [7/7] Verifying Grafana and Frontend (127.0.0.1:4173) readiness..." -ForegroundColor Cyan
    $grafHealth = Invoke-RestMethod -Uri "http://127.0.0.1:3000/api/health" -TimeoutSec 5
    if ($grafHealth.database -ne "ok") {
        throw "Grafana health check failed: database=$($grafHealth.database)"
    }
    Write-Host "    Grafana OK (database: $($grafHealth.database), version: $($grafHealth.version))" -ForegroundColor Green

    $frontendResp = Invoke-WebRequest -Uri "http://127.0.0.1:4173/" -UseBasicParsing -TimeoutSec 5
    if ($frontendResp.StatusCode -ne 200 -or $frontendResp.Content -notmatch "OpsPilot") {
        throw "Frontend check failed on http://127.0.0.1:4173/ (status: $($frontendResp.StatusCode))."
    }
    $frontendApiHealth = Invoke-RestMethod -Uri "http://127.0.0.1:4173/api/health" -TimeoutSec 5
    if ($frontendApiHealth.status -ne "ok") {
        throw "Frontend /api/health proxy check failed."
    }
    Write-Host "    Frontend OK on http://127.0.0.1:4173/ (API proxy /api/health status: $($frontendApiHealth.status))" -ForegroundColor Green

    docker compose ps
    Write-Host "`nLocal deployment and health validation completed successfully." -ForegroundColor Green
} finally {
    Pop-Location
}
