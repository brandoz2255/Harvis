#Requires -Version 5.1
<#
.SYNOPSIS
Bootstraps Harvis on a native Windows host using Docker Desktop.

.DESCRIPTION
The application containers and compose file are shared with Ubuntu. This
script contains only Windows host setup that cannot run in Bash. It checks for
Docker Desktop and connects the containers to an LLM already running on Windows.
##>
[CmdletBinding()]
param(
    [switch]$Yes,
    [switch]$CheckOnly,
    [switch]$NoLaunch,
    [switch]$VerifyGpu,
    [string]$LlmUrl
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSCommandPath
Set-Location $repoRoot
$envPath = Join-Path $repoRoot '.env'

function Assert-WindowsHost {
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
        throw 'install.ps1 is for native Windows. On Ubuntu, run ./install.sh instead.'
    }
}

function Assert-DockerDesktop {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'Docker Desktop is not installed or docker.exe is not on PATH. Install Docker Desktop, enable WSL 2 integration, then reopen PowerShell.'
    }
    & docker version --format '{{.Server.Version}}' | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw 'Docker Desktop is installed but its Linux container engine is not running. Start Docker Desktop and wait for it to finish starting.'
    }
    & docker compose version | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw 'Docker Compose v2 is unavailable. Update Docker Desktop and try again.'
    }
    $operatingSystem = (& docker info --format '{{.OperatingSystem}}').Trim()
    if ($operatingSystem -notmatch 'Docker Desktop') {
        Write-Warning "Docker reports '$operatingSystem'. Native Windows is supported through Docker Desktop with Linux containers."
    }
}

function Get-JsonResponse {
    param([Parameter(Mandatory = $true)][string]$Url)
    try { return Invoke-RestMethod -Uri $Url -Method Get -TimeoutSec 3 }
    catch { return $null }
}

function Find-HostLlm {
    $candidates = @(
        [pscustomobject]@{ Name = 'Ollama'; Port = 11434; Path = '/api/tags'; Property = 'models' },
        [pscustomobject]@{ Name = 'LM Studio'; Port = 1234; Path = '/v1/models'; Property = 'data' },
        [pscustomobject]@{ Name = 'vLLM'; Port = 8000; Path = '/v1/models'; Property = 'data' },
        [pscustomobject]@{ Name = 'OpenAI-compatible server'; Port = 8080; Path = '/v1/models'; Property = 'data' }
    )
    foreach ($candidate in $candidates) {
        $response = Get-JsonResponse "http://127.0.0.1:$($candidate.Port)$($candidate.Path)"
        if ($null -ne $response -and $null -ne $response.PSObject.Properties[$candidate.Property]) {
            return [pscustomobject]@{ Name = $candidate.Name; Url = "http://host.docker.internal:$($candidate.Port)" }
        }
    }
    return $null
}

function Get-DotEnvValue {
    param([Parameter(Mandatory = $true)][string]$Key)
    if (-not (Test-Path $envPath)) { return '' }
    $prefix = "$Key="
    $line = Get-Content $envPath | Where-Object { $_.StartsWith($prefix) } | Select-Object -First 1
    if ($null -eq $line) { return '' }
    return $line.Substring($prefix.Length)
}

function Set-DotEnvValue {
    param([Parameter(Mandatory = $true)][string]$Key, [Parameter(Mandatory = $true)][string]$Value)
    $prefix = "$Key="
    $lines = if (Test-Path $envPath) { @(Get-Content $envPath) } else { @() }
    $written = $false
    $output = foreach ($line in $lines) {
        if ($line.StartsWith($prefix)) {
            if (-not $written) { $written = $true; "$Key=$Value" }
        }
        else { $line }
    }
    if (-not $written) { $output += "$Key=$Value" }
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($envPath, (($output -join [Environment]::NewLine) + [Environment]::NewLine), $encoding)
}

function Remove-DotEnvValue {
    param([Parameter(Mandatory = $true)][string]$Key)
    if (-not (Test-Path $envPath)) { return }
    $prefix = "$Key="
    $output = @(Get-Content $envPath | Where-Object { -not $_.StartsWith($prefix) })
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($envPath, (($output -join [Environment]::NewLine) + [Environment]::NewLine), $encoding)
}

function New-RandomHex {
    param([Parameter(Mandatory = $true)][int]$Bytes)
    $buffer = New-Object byte[] $Bytes
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($buffer) } finally { $rng.Dispose() }
    return (([System.BitConverter]::ToString($buffer) -replace '-', '').ToLowerInvariant())
}

function New-FernetKey {
    $buffer = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($buffer) } finally { $rng.Dispose() }
    return [Convert]::ToBase64String($buffer).Replace('+', '-').Replace('/', '_')
}

function Initialize-HarvisEnvironment {
    param([AllowNull()][string]$ResolvedLlmUrl)
    if (-not (Test-Path $envPath)) { Copy-Item '.env.example' '.env' }
    if (-not (Get-DotEnvValue 'JWT_SECRET')) { Set-DotEnvValue 'JWT_SECRET' (New-RandomHex 32) }
    if (-not (Get-DotEnvValue 'FERNET_KEY')) { Set-DotEnvValue 'FERNET_KEY' (New-FernetKey) }
    if (-not (Get-DotEnvValue 'POSTGRES_PASSWORD')) { Set-DotEnvValue 'POSTGRES_PASSWORD' (New-RandomHex 24) }
    if (-not (Get-DotEnvValue 'OPENCLAW_GATEWAY_TOKEN')) { Set-DotEnvValue 'OPENCLAW_GATEWAY_TOKEN' (New-RandomHex 24) }
    if (-not (Get-DotEnvValue 'MESSAGING_GATEWAY_TOKEN')) { Set-DotEnvValue 'MESSAGING_GATEWAY_TOKEN' (New-RandomHex 24) }
    if ($ResolvedLlmUrl) { Set-DotEnvValue 'HARVIS_LLM_BASE_URL' $ResolvedLlmUrl }

    $runtimes = (& docker info --format '{{json .Runtimes}}')
    if ($runtimes -match '"nvidia"') { Set-DotEnvValue 'HARVIS_GPU_RUNTIME' 'nvidia' }
    else { Remove-DotEnvValue 'HARVIS_GPU_RUNTIME' }
}

function Ensure-HarvisNetwork {
    & docker network inspect ollama-n8n-network *> $null
    if ($LASTEXITCODE -ne 0) {
        & docker network create ollama-n8n-network | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the ollama-n8n-network Docker network.' }
    }
}

function Sync-DatabasePassword {
    & docker compose up -d pgsql | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL did not start, so its password could not be synchronized.' }

    # The password stays in the container environment; it is never printed or
    # interpolated into a host command.
    $syncCommand = 'printf "ALTER ROLE pguser WITH PASSWORD :' + "'" + 'pw' + "'" + ';\n" | psql -q -v ON_ERROR_STOP=1 -v pw="$POSTGRES_PASSWORD" -U pguser -d postgres'
    for ($attempt = 1; $attempt -le 15; $attempt++) {
        & docker compose exec -T pgsql sh -c $syncCommand *> $null
        if ($LASTEXITCODE -eq 0) { return }
        Start-Sleep -Seconds 2
    }
    throw 'PostgreSQL started but did not become ready in time.'
}

function Test-HarvisGpu {
    Write-Host 'Checking NVIDIA GPU access from Docker...'
    & docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
    if ($LASTEXITCODE -ne 0) {
        throw 'Docker cannot see the NVIDIA GPU. Update the Windows NVIDIA driver, enable Docker Desktop WSL 2 integration, then retry this command.'
    }
}

function Wait-ForHarvis {
    for ($attempt = 1; $attempt -le 36; $attempt++) {
        try {
            $response = Invoke-WebRequest -Uri 'http://localhost:9000/harvis/' -UseBasicParsing -TimeoutSec 8
            if ($response.StatusCode -eq 200) { return }
        }
        catch { }
        Start-Sleep -Seconds 5
    }
    throw 'Harvis did not become reachable at http://localhost:9000/harvis/. Run docker compose logs --tail=200 to inspect the startup error.'
}

Assert-WindowsHost
Assert-DockerDesktop

if ($CheckOnly -and $VerifyGpu) {
    throw '-CheckOnly does not pull the CUDA image. Run .\install.ps1 -VerifyGpu after the preflight check.'
}
if ($VerifyGpu) { Test-HarvisGpu }

$resolvedLlmUrl = ''
if ($LlmUrl) {
    try { $parsedLlmUrl = [Uri]$LlmUrl } catch { throw "-LlmUrl must be an http(s) URL, not '$LlmUrl'." }
    if ($parsedLlmUrl.Scheme -notin @('http', 'https')) { throw "-LlmUrl must be an http(s) URL, not '$LlmUrl'." }
    if ($parsedLlmUrl.Host -in @('localhost', '127.0.0.1', '::1')) {
        throw 'Containers cannot use localhost for a Windows-hosted LLM. Use http://host.docker.internal:PORT instead.'
    }
    $resolvedLlmUrl = $LlmUrl.TrimEnd('/')
}
else {
    $savedLlmUrl = Get-DotEnvValue 'HARVIS_LLM_BASE_URL'
    if ($savedLlmUrl) {
        $resolvedLlmUrl = $savedLlmUrl
        Write-Host "Using the saved LLM endpoint: $resolvedLlmUrl"
    }
    else {
        $detectedLlm = Find-HostLlm
        if ($detectedLlm) {
            $resolvedLlmUrl = $detectedLlm.Url
            Write-Host "Found $($detectedLlm.Name) on the Windows host. Containers will use $resolvedLlmUrl"
        }
        else {
            Write-Warning 'No local LLM server was found. Harvis will start, but chat and voice require an LLM endpoint. Re-run with -LlmUrl http://host.docker.internal:PORT after starting Ollama, LM Studio, or another compatible server.'
        }
    }
}

if ($CheckOnly) {
    Write-Host 'Windows preflight passed: Docker Desktop and Docker Compose are available.'
    Write-Host 'Kubernetes deployment is Linux-only; use the Ubuntu installer on a Linux node for k3s.'
    exit 0
}

if (-not $Yes) {
    $answer = Read-Host 'Create/update .env and build/start Harvis now? [Y/n]'
    if ($answer -match '^[Nn]') { Write-Host 'No changes made.'; exit 0 }
}

Initialize-HarvisEnvironment $resolvedLlmUrl
Ensure-HarvisNetwork
if ($NoLaunch) { Write-Host 'Environment initialized. Run .\install.ps1 -Yes to build and start Harvis.'; exit 0 }

Sync-DatabasePassword
& docker compose up --build -d
if ($LASTEXITCODE -ne 0) { throw 'Harvis containers did not start. Run docker compose logs --tail=200 to inspect the failure.' }
& docker compose restart nginx | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Harvis started, but nginx could not be restarted. Run docker compose logs nginx to inspect the failure.' }

Wait-ForHarvis
Write-Host 'Harvis is ready at http://localhost:9000/harvis/'
Write-Host 'Native Windows uses Docker Desktop. For k3s, deploy from Ubuntu or another Linux host.'
