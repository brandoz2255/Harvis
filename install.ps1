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
    [string]$LlmUrl,
    # Who can reach Harvis; left out, a new install is local and one whose port
    # 9000 is open right now keeps it open (Select-DefaultExposure). Same meaning as
    # install.sh --expose: local (this computer), lan (your network, sign-up
    # closed once the admin exists), tunnel (experimental: internet via Cloudflare
    # Tunnel + Access), lan+tunnel (experimental: both at once).
    [ValidateSet('local', 'lan', 'tunnel', 'lan+tunnel')][string]$Expose,
    # Only these people get through the tunnel, even if the Access policy in
    # Cloudflare is wider: emails or @domain, comma-separated; off removes the
    # list. Same as install.sh --allow-emails.
    [string]$AllowEmails,
    # A new 6-digit first-admin code for a shared server with no admin yet.
    # Same as install.sh --admin-code.
    [switch]$AdminCode,
    # Lend this computer's Ollama to a Harvis server elsewhere on the network:
    # shows a 6-digit PIN to type into that Harvis. Same as install.sh --inference-node.
    [switch]$InferenceNode
)

$ErrorActionPreference = 'Stop'
# ValidateSet ignores case; .env and every comparison below use lower case.
if ($Expose) { $Expose = $Expose.ToLowerInvariant() }
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
    # The last assignment wins and surrounding quotes are dropped, as in compose.
    $line = Get-Content $envPath | Where-Object { $_.StartsWith($prefix) } | Select-Object -Last 1
    if ($null -eq $line) { return '' }
    $value = $line.Substring($prefix.Length)
    if ($value -match '^"(.*)"$' -or $value -match "^'(.*)'$") { $value = $Matches[1] }
    return $value
}

function Set-DotEnvValue {
    param([Parameter(Mandatory = $true)][string]$Key, [Parameter(Mandatory = $true)][string]$Value)
    $prefix = "$Key="
    $lines = if (Test-Path $envPath) { @(Get-Content $envPath) } else { @() }
    $written = $false
    $output = @(foreach ($line in $lines) {
        if ($line.StartsWith($prefix)) {
            if (-not $written) { $written = $true; "$Key=$Value" }
        }
        else { $line }
    })
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

function Get-CurrentExposure {
    if ($Expose) { return $Expose }
    $saved = (Get-DotEnvValue 'HARVIS_EXPOSURE').Trim('"', "'").ToLowerInvariant()
    if ($saved) { return $saved }
    return 'local'
}

function Test-TcpReach {
    param([string]$HostName, [int]$Port)
    $client = New-Object System.Net.Sockets.TcpClient
    try { return $client.ConnectAsync($HostName, $Port).Wait(5000) }
    catch { return $false }
    finally { $client.Dispose() }
}

# The backend refuses to start a shared server on a guessable signing secret
# (python_back_end/plugins/exposure/mode.py).
function Test-WeakJwtSecret {
    param([AllowEmptyString()][string]$Value)
    $v = $Value.Trim()
    $known = @('', 'key', 'secret', 'changeme', 'change-me', 'your-secret-key', 'your_jwt_secret', 'jwt_secret')
    return ($known -contains $v.ToLowerInvariant()) -or $v.Length -lt 32
}

# Native commands whose stderr is ordinary output (compose progress, cloudflared
# logs). Windows PowerShell 5.1 turns redirected stderr into errors, which
# $ErrorActionPreference = 'Stop' would make fatal.
function Invoke-Quietly {
    param([scriptblock]$Command)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { return (& $Command) } finally { $ErrorActionPreference = $previous }
}

# Same rule as install.sh choose_default_exposure: a first install is local; an
# install whose nginx publishes port 9000 on every address right now keeps it
# open (compose now defaults it to 127.0.0.1) until its owner picks. A recorded
# lan whose bind went missing is re-applied rather than going dark.
$script:PinLegacyPublic = $false
$script:ExposeDefaulted = $false
function Select-DefaultExposure {
    if ($script:Expose) { return }
    $cur = (Get-DotEnvValue 'HARVIS_EXPOSURE').Trim('"', "'").ToLowerInvariant()
    $bind = (Get-DotEnvValue 'HARVIS_BIND_ADDR_PUBLIC').Trim('"', "'")
    if ($cur -eq 'lan' -and $bind -ne '0.0.0.0') { $script:Expose = 'lan'; return }
    if ($cur -or $bind) { return }
    $stack = if ($env:HARVIS_STACK_NAME) { $env:HARVIS_STACK_NAME } else { (Get-DotEnvValue 'HARVIS_STACK_NAME').Trim('"', "'") }
    if (-not $stack) { $stack = 'harvis' }
    $ids = @(Invoke-Quietly { & docker ps -q --filter "label=com.docker.compose.project=$stack" --filter 'label=com.docker.compose.service=nginx' 2>$null })
    $binds = if ($ids.Count -gt 0) {
        @(Invoke-Quietly { & docker inspect -f '{{range $p, $b := .HostConfig.PortBindings}}{{range $b}}[{{.HostIp}}] {{end}}{{end}}' @ids 2>$null })
    } else { @() }
    $open = @(($binds -join ' ') -split '\s+' | Where-Object { $_ -in @('[]', '[0.0.0.0]', '[::]') }).Count -gt 0
    if ($open) { $script:PinLegacyPublic = $true }
    else { $script:Expose = 'local'; $script:ExposeDefaulted = $true }
}

function Get-AllowEmails {
    # What .env will hold after this run, lower-case with no spaces.
    if ($AllowEmails -eq 'off') { return '' }
    $raw = if ($AllowEmails) { $AllowEmails } else { Get-DotEnvValue 'HARVIS_CF_ACCESS_ALLOWED_EMAILS' }
    return (@(($raw -replace '\s', '').ToLowerInvariant() -split ',' | Where-Object { $_ }) -join ',')
}

function Assert-AllowEmails {
    if (-not $AllowEmails -or $AllowEmails -eq 'off') { return }
    $items = @(($AllowEmails -replace '\s', '') -split ',' | Where-Object { $_ })
    $bad = @($items | Where-Object { $_ -notmatch '^([A-Za-z0-9._%+-]+)?@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$' })
    if ($AllowEmails -match '[\r\n]' -or $items.Count -eq 0 -or $bad.Count -gt 0) {
        throw '-AllowEmails takes emails or @domain, comma-separated (or off). Nothing was changed.'
    }
}

function Show-ExposureChecks {
    $mode = Get-CurrentExposure
    $bind = (Get-DotEnvValue 'HARVIS_BIND_ADDR_PUBLIC').Trim('"', "'")
    if ($mode -eq 'local' -and -not $Expose -and ($bind -eq '0.0.0.0' -or $script:PinLegacyPublic)) {
        Write-Warning 'Port 9000 is open to your network and the first sign-up becomes admin. Choose with -Expose local (this computer only) or -Expose lan (your network, sign-up closed once you are admin).'
    }
    else { Write-Host "Exposure: $mode" }
    if ((Get-DotEnvValue 'HARVIS_BIND_ADDR') -eq '0.0.0.0') {
        if ($mode -eq 'lan') {
            Write-Warning 'HARVIS_BIND_ADDR=0.0.0.0 opens the backend (8000), notebook and TTS ports with no sign-in. Remove it from .env so only port 9000 leaves this machine.'
        }
        elseif ($Expose) { Write-Warning 'HARVIS_BIND_ADDR=0.0.0.0 opens the backend (8000), notebook and TTS ports; it will be removed.' }
        else { Write-Warning 'HARVIS_BIND_ADDR=0.0.0.0 opens the backend (8000), notebook and TTS ports with no sign-in. Remove it from .env, or run with -Expose local to do it for you.' }
    }
    if ($mode -ne 'local' -and $env:JWT_SECRET -and (Test-WeakJwtSecret $env:JWT_SECRET)) {
        throw 'JWT_SECRET in your environment is too weak to share Harvis. Remove it (Harvis keeps a strong one in .env) and run again.'
    }
    if ($mode -ne 'local' -and (Get-DotEnvValue 'HARVIS_OWUI_ENABLE_SIGNUP').Trim('"', "'").ToLowerInvariant() -eq 'true') {
        Write-Warning '.env keeps sign-up open: anyone who reaches port 9000 can make an account. Remove HARVIS_OWUI_ENABLE_SIGNUP from .env, and check Settings > General, which can open it too.'
    }
    if ($mode -notin @('tunnel', 'lan+tunnel')) { return }
    # The network lock (install.sh --tunnel-networks) needs NetworkManager and
    # systemd. Here the tunnel would run on any network, so refuse rather than
    # quietly drop the lock from a .env copied off a Linux machine.
    if ((Get-DotEnvValue 'HARVIS_TUNNEL_NETWORKS').Trim()) {
        throw "This .env has a network lock (HARVIS_TUNNEL_NETWORKS) that only works on Linux with NetworkManager. Run the tunnel from that Linux machine, or remove HARVIS_TUNNEL_NETWORKS from .env and run again with -Expose $mode for the regular profile here. Nothing was changed."
    }
    $listed = Get-AllowEmails
    if ($listed) { Write-Host "Named people only: $(@($listed -split ',').Count) on HARVIS_CF_ACCESS_ALLOWED_EMAILS." }
    else { Write-Warning 'Anyone your Cloudflare Access policy lets in can open the Harvis sign-in. Name the people Harvis accepts with -AllowEmails you@school.edu,colleague@school.edu (or @school.edu for a whole domain).' }
    try {
        if (@(Get-NetConnectionProfile -ErrorAction Stop | Where-Object { $_.Name -match '^eduroam' }).Count -gt 0) {
            Write-Warning 'eduroam is connected. Disconnect it and use the lab network so the tunnel does not cross the campus network.'
        }
    }
    catch { }
    if (Test-TcpReach 'region1.v2.argotunnel.com' 7844) { Write-Host 'Cloudflare reachable on port 7844.' }
    else { Write-Warning 'Could not reach Cloudflare on port 7844. This network may block the tunnel; try the wired lab network.' }
}

function Get-TunnelInputs {
    # Explicit environment wins, then .env, then a prompt. Checked before .env
    # is touched: a stray newline or quote here would corrupt it.
    $token = if ($env:HARVIS_TUNNEL_TOKEN) { $env:HARVIS_TUNNEL_TOKEN } else { Get-DotEnvValue 'HARVIS_TUNNEL_TOKEN' }
    $team = if ($env:HARVIS_CF_ACCESS_TEAM_DOMAIN) { $env:HARVIS_CF_ACCESS_TEAM_DOMAIN } else { Get-DotEnvValue 'HARVIS_CF_ACCESS_TEAM_DOMAIN' }
    $aud = if ($env:HARVIS_CF_ACCESS_AUD) { $env:HARVIS_CF_ACCESS_AUD } else { Get-DotEnvValue 'HARVIS_CF_ACCESS_AUD' }
    if ((-not $token -or -not $team -or -not $aud) -and $Yes) {
        throw "-Expose $Expose with -Yes needs HARVIS_TUNNEL_TOKEN, HARVIS_CF_ACCESS_TEAM_DOMAIN (<team>.cloudflareaccess.com) and HARVIS_CF_ACCESS_AUD in the environment or .env. Nothing was changed."
    }
    if (-not $token) {
        $secure = Read-Host 'Cloudflare tunnel token (input hidden)' -AsSecureString
        $token = (New-Object System.Net.NetworkCredential('', $secure)).Password
    }
    if (-not $team) { $team = Read-Host 'Access team domain (<team>.cloudflareaccess.com)' }
    if (-not $aud) { $aud = Read-Host 'Access application AUD tag' }
    $token = ($token -replace '\s', '')
    $team = (($team -replace '\s', '').ToLowerInvariant() -replace '^https?://', '') -replace '/.*$', ''
    $aud = ($aud -replace '\s', '')
    if ($token -notmatch '^[A-Za-z0-9+/=_-]{40,}$') { throw 'That tunnel token does not look right (it is a long base64 string). Nothing was changed.' }
    if ($team -notmatch '^[a-z0-9-]+(\.[a-z0-9-]+)+$') { throw 'The team domain should look like myteam.cloudflareaccess.com. Nothing was changed.' }
    if ($aud -notmatch '^[A-Za-z0-9]{16,}$') { throw 'The AUD tag should be letters and digits only. Nothing was changed.' }
    return [pscustomobject]@{ Token = $token; Team = $team; Aud = $aud }
}

function Set-TunnelProfile {
    param([bool]$On)
    $current = (Get-DotEnvValue 'COMPOSE_PROFILES').Trim('"', "'")
    $profiles = @($current -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ -and $_ -ne 'tunnel' })
    if ($On) { $profiles += 'tunnel' }
    $joined = $profiles -join ','
    if ($joined -eq $current) { return }
    if ($joined) { Set-DotEnvValue 'COMPOSE_PROFILES' $joined } else { Remove-DotEnvValue 'COMPOSE_PROFILES' }
}

function Close-Signup {
    # Only when unset: an operator who chose open sign-up keeps it.
    if (-not (Get-DotEnvValue 'HARVIS_OWUI_ENABLE_SIGNUP')) {
        Set-DotEnvValue 'HARVIS_OWUI_ENABLE_SIGNUP' 'false'
        Set-DotEnvValue 'HARVIS_SIGNUP_CLOSED_BY_EXPOSE' '1'
        Write-Host 'Closed self-serve sign-up (open it in Settings > General while people register).'
    }
}

function Open-Signup {
    # Only what Close-Signup closed; an operator's own setting stays.
    if (Get-DotEnvValue 'HARVIS_SIGNUP_CLOSED_BY_EXPOSE') {
        Remove-DotEnvValue 'HARVIS_OWUI_ENABLE_SIGNUP'
        Remove-DotEnvValue 'HARVIS_SIGNUP_CLOSED_BY_EXPOSE'
        Write-Host 'Reopened self-serve sign-up (closed when Harvis was shared).'
    }
}

function Set-AllowEmails {
    if (-not $AllowEmails) { return }
    if ($AllowEmails -eq 'off') {
        if (Get-DotEnvValue 'HARVIS_CF_ACCESS_ALLOWED_EMAILS') {
            Remove-DotEnvValue 'HARVIS_CF_ACCESS_ALLOWED_EMAILS'
            Write-Host 'Removed the named-people list (Cloudflare Access alone decides who gets in).'
        }
        return
    }
    Set-DotEnvValue 'HARVIS_CF_ACCESS_ALLOWED_EMAILS' (Get-AllowEmails)
    Write-Host 'Only the named people get through the tunnel (HARVIS_CF_ACCESS_ALLOWED_EMAILS).'
}

function Set-HarvisExposure {
    param($Tunnel)
    Set-AllowEmails
    if ($script:PinLegacyPublic) {
        Set-DotEnvValue 'HARVIS_BIND_ADDR_PUBLIC' '0.0.0.0'
        Write-Host 'Kept port 9000 open to your network, as before. Close it with -Expose local.'
        return
    }
    if (-not $Expose) { return }
    if ($Expose -in @('tunnel', 'lan+tunnel')) {
        Write-Warning "-Expose $Expose is experimental: the internet entrance through a Cloudflare Tunnel has been tested against a stand-in, never against a real Cloudflare account. For a server people use today, choose lan."
    }
    if ($script:ExposeDefaulted) {
        Write-Host 'Harvis is reachable from this computer only. Share it with -Expose lan.'
    }
    if ($Expose -ne 'lan' -and (Get-DotEnvValue 'HARVIS_BIND_ADDR') -eq '0.0.0.0') {
        Remove-DotEnvValue 'HARVIS_BIND_ADDR'
        Write-Host 'Removed HARVIS_BIND_ADDR=0.0.0.0 (backend, notebook and TTS ports back on 127.0.0.1).'
    }
    $was = (Get-DotEnvValue 'HARVIS_EXPOSURE').Trim('"', "'").ToLowerInvariant()
    Set-DotEnvValue 'HARVIS_EXPOSURE' $Expose
    if ($Expose -ne 'local' -and -not $env:JWT_SECRET -and (Test-WeakJwtSecret (Get-DotEnvValue 'JWT_SECRET'))) {
        Set-DotEnvValue 'JWT_SECRET' (New-RandomHex 32)
        Write-Host 'Replaced a weak JWT_SECRET (everyone signs in again).'
    }
    switch ($Expose) {
        'local' {
            Set-DotEnvValue 'HARVIS_BIND_ADDR_PUBLIC' '127.0.0.1'
            Open-Signup
            Set-TunnelProfile $false
        }
        'lan' {
            Set-DotEnvValue 'HARVIS_BIND_ADDR_PUBLIC' '0.0.0.0'
            Close-Signup
            Set-TunnelProfile $false
        }
        'tunnel' {
            Set-DotEnvValue 'HARVIS_BIND_ADDR_PUBLIC' '127.0.0.1'
            Close-Signup
            # Visitors arrive over HTTPS, so the sign-in cookie can insist on it.
            Set-DotEnvValue 'HARVIS_COOKIE_SECURE' 'true'
            Set-DotEnvValue 'HARVIS_TUNNEL_TOKEN' $Tunnel.Token
            Set-DotEnvValue 'HARVIS_CF_ACCESS_TEAM_DOMAIN' $Tunnel.Team
            Set-DotEnvValue 'HARVIS_CF_ACCESS_AUD' $Tunnel.Aud
            # Left by the Linux network lock; here Docker restarts the tunnel as usual.
            Remove-DotEnvValue 'HARVIS_TUNNEL_RESTART'
            Set-TunnelProfile $true
        }
        'lan+tunnel' {
            Set-DotEnvValue 'HARVIS_BIND_ADDR_PUBLIC' '0.0.0.0'
            Close-Signup
            # The LAN signs in over plain http; nginx marks the cookie Secure on
            # the tunnel entrance alone.
            Remove-DotEnvValue 'HARVIS_COOKIE_SECURE'
            Set-DotEnvValue 'HARVIS_TUNNEL_TOKEN' $Tunnel.Token
            Set-DotEnvValue 'HARVIS_CF_ACCESS_TEAM_DOMAIN' $Tunnel.Team
            Set-DotEnvValue 'HARVIS_CF_ACCESS_AUD' $Tunnel.Aud
            Remove-DotEnvValue 'HARVIS_TUNNEL_RESTART'
            Set-TunnelProfile $true
        }
    }
    # Leaving tunnel mode: the secure-only cookie would break sign-in over plain
    # http://<lan-ip>:9000, and the tunnel should close now.
    if ($was -in @('tunnel', 'lan+tunnel') -and $Expose -notin @('tunnel', 'lan+tunnel')) {
        Remove-DotEnvValue 'HARVIS_COOKIE_SECURE'
        Invoke-Quietly { & docker compose --profile tunnel rm -sf cloudflared *> $null }
        if ($LASTEXITCODE -eq 0) { Write-Host 'Stopped the Cloudflare Tunnel.' }
        else { Write-Warning 'Could not stop the Cloudflare Tunnel; stop it with: docker compose --profile tunnel rm -sf cloudflared' }
    }
    Write-Host "Exposure set to $Expose."
}

function Show-TunnelStatus {
    if ((Get-CurrentExposure) -notin @('tunnel', 'lan+tunnel')) { return }
    $prefix = if ($env:HARVIS_CONTAINER_PREFIX) { $env:HARVIS_CONTAINER_PREFIX } else { Get-DotEnvValue 'HARVIS_CONTAINER_PREFIX' }
    $name = "${prefix}harvis-cloudflared"
    $connected = $false
    for ($attempt = 1; $attempt -le 15 -and -not $connected; $attempt++) {
        $logs = (Invoke-Quietly { & docker logs --tail 50 $name 2>&1 }) -join "`n"
        if ($logs -match 'Registered tunnel connection') { $connected = $true } else { Start-Sleep -Seconds 2 }
    }
    if ($connected) { Write-Host 'Tunnel connected to Cloudflare.' }
    else { Write-Warning "Tunnel not connected yet. See: docker logs $name" }
    Write-Host 'In Cloudflare, the public hostname must point to http://nginx:8081 and have an Access application in front of it.'
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
    Set-TunnelSubnet
}

function Test-CidrOverlap {
    param([string]$A, [string]$B)
    $toInt = { param($ip) $o = $ip.Split('.') | ForEach-Object { [uint32]$_ }; ($o[0] -shl 24) + ($o[1] -shl 16) + ($o[2] -shl 8) + $o[3] }
    $bits = [Math]::Min([int]$A.Split('/')[1], [int]$B.Split('/')[1])
    $mask = if ($bits -eq 0) { [uint32]0 } else { [uint32](([uint64]4294967295 -shl (32 - $bits)) -band [uint64]4294967295) }
    return ((& $toInt $A.Split('/')[0]) -band $mask) -eq ((& $toInt $B.Split('/')[0]) -band $mask)
}

# tunnel-edge (docker-compose.yaml) gets a fixed /29 so Docker never hands it a
# range of its own choosing. Picked once per install: a second stack on this
# machine would otherwise ask for the same /29 and fail to start.
function Set-TunnelSubnet {
    if ($env:HARVIS_TUNNEL_SUBNET) { Set-DotEnvValue 'HARVIS_TUNNEL_SUBNET' $env:HARVIS_TUNNEL_SUBNET; return }
    if (Get-DotEnvValue 'HARVIS_TUNNEL_SUBNET') { return }
    $stack = if ($env:HARVIS_STACK_NAME) { $env:HARVIS_STACK_NAME } else { (Get-DotEnvValue 'HARVIS_STACK_NAME').Trim('"', "'") }
    if (-not $stack) { $stack = 'harvis' }
    # Already created: keep its range, or compose refuses the changed network.
    $own = @(@(Invoke-Quietly { & docker network inspect "${stack}_tunnel-edge" --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}' 2>$null }) | Where-Object { $_ })
    if ($own) { Set-DotEnvValue 'HARVIS_TUNNEL_SUBNET' "$($own[0])"; return }
    $ids = @(Invoke-Quietly { & docker network ls -q 2>$null })
    $taken = if ($ids.Count -gt 0) {
        @(Invoke-Quietly { & docker network inspect @ids --format '{{range .IPAM.Config}}{{.Subnet}} {{end}}' 2>$null }) -split '\s+' | Where-Object { $_ -match '^\d+\.\d+\.\d+\.\d+/\d+$' }
    } else { @() }
    foreach ($i in 0..31) {
        $cand = "10.213.82.$($i * 8)/29"
        if (-not ($taken | Where-Object { Test-CidrOverlap $cand $_ })) { Set-DotEnvValue 'HARVIS_TUNNEL_SUBNET' $cand; return }
    }
    Write-Warning 'No free /29 in 10.213.82.0/24 for the tunnel network; set HARVIS_TUNNEL_SUBNET in .env.'
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

function Get-FirstAdminCode {
    # The backend's own CLI makes the code (plugins/exposure/first_admin.py); a
    # fresh one replaces any older code.
    $out = (& docker compose exec -T backend python -m plugins.exposure.first_admin 2>$null) -join "`n"
    if ($LASTEXITCODE -ne 0) { return $null }
    $m = [regex]::Match($out, '\b\d{6}\b')
    if ($m.Success) { return $m.Value } else { return $null }
}

function Write-HostOnly([string]$text) {
    # [Console] output stays out of Start-Transcript logs, unlike Write-Host.
    [Console]::WriteLine($text)
}

function Show-FirstAdmin {
    try {
        $status = Invoke-RestMethod -Uri 'http://localhost:9000/api/setup/status' -TimeoutSec 8
    }
    catch { return }
    if (-not $status.needs_setup) { Write-Host 'Instance already has an admin; sign in as usual.'; return }
    if (Get-DotEnvValue 'HARVIS_SETUP_CODE') {
        Write-Host 'No admin yet. This instance sets HARVIS_SETUP_CODE in .env, so the first sign-up will ask for it.'
        return
    }
    $mode = Get-DotEnvValue 'HARVIS_EXPOSURE'
    if (-not $mode -or $mode -eq 'local') {
        Write-Host 'No admin yet: the first account you sign up with becomes the admin.'
        return
    }
    $code = Get-FirstAdminCode
    if (-not $code) {
        Write-Warning 'No admin yet. The first sign-up needs a 6-digit code, and making one failed just now. Try again in a minute: .\install.ps1 -AdminCode'
        return
    }
    Write-Host 'No admin yet. Anyone on your network can open the sign-up page, so the first account needs this code:'
    Write-HostOnly "    first-admin code: $code"
    Write-Host '(shown on this screen only; five wrong tries retire it. Get a new one with .\install.ps1 -AdminCode)'
}

if ($InferenceNode) {
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) { $py = Get-Command py -ErrorAction SilentlyContinue }
    if (-not $py) { throw 'Python 3 is needed for the inference node. Install it from python.org and run this again.' }
    Write-Host 'In Harvis, open Settings > Models > Add a computer, and enter this computer''s address and the PIN below. Ctrl-C stops the node.'
    & $py.Source (Join-Path $repoRoot 'scripts\inference-node\harvis_node.py')
    exit $LASTEXITCODE
}

Assert-WindowsHost
Assert-DockerDesktop

if ($AdminCode) {
    $code = Get-FirstAdminCode
    if (-not $code) { throw 'No code was made. Is Harvis running, and does this server still have no admin? (docker compose ps)' }
    Write-HostOnly "First-admin code: $code"
    Write-Host '(shown on this screen only; the old code no longer works)'
    exit 0
}

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

Assert-AllowEmails
Select-DefaultExposure
Show-ExposureChecks

if ($CheckOnly) {
    Write-Host 'Windows preflight passed: Docker Desktop and Docker Compose are available.'
    Write-Host 'Kubernetes deployment is Linux-only; use the Ubuntu installer on a Linux node for k3s.'
    exit 0
}

if (-not $Yes) {
    $answer = Read-Host 'Create/update .env and build/start Harvis now? [Y/n]'
    if ($answer -match '^[Nn]') { Write-Host 'No changes made.'; exit 0 }
}

$tunnelInputs = if ($Expose -in @('tunnel', 'lan+tunnel')) { Get-TunnelInputs } else { $null }
Initialize-HarvisEnvironment $resolvedLlmUrl
Set-HarvisExposure $tunnelInputs
Ensure-HarvisNetwork
if ($NoLaunch) { Write-Host 'Environment initialized. Run .\install.ps1 -Yes to build and start Harvis.'; exit 0 }

Sync-DatabasePassword
& docker compose up --build -d
if ($LASTEXITCODE -ne 0) { throw 'Harvis containers did not start. Run docker compose logs --tail=200 to inspect the failure.' }
& docker compose restart nginx | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Harvis started, but nginx could not be restarted. Run docker compose logs nginx to inspect the failure.' }

Wait-ForHarvis
Write-Host 'Harvis is ready at http://localhost:9000/harvis/'
Show-FirstAdmin
Show-TunnelStatus
Write-Host 'Native Windows uses Docker Desktop. For k3s, deploy from Ubuntu or another Linux host.'
