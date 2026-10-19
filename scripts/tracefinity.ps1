<#
.SYNOPSIS
Run Tracefinity for SolidSeas' Gridfinity tools: in Docker Desktop, on this PC only.

.DESCRIPTION
Starts the container named tracefinity, making it the first time from the image named
below, the way SolidSeas expects it (docs/GRIDFINITY.md):

- published on 127.0.0.1 only, so nothing else on the network reaches it;
- AUTH_MODE=open: one library and no sign-in, which is safe only because of the line above;
- its library (tools, bins, the photos it was given) in
  %LOCALAPPDATA%\SolidSeas\tracefinity\storage, and the image models it downloads from
  GitHub the first time it traces in ...\models, so neither is lost with the container;
- started again with Docker Desktop (--restart unless-stopped).

Run it again to start the container when it is stopped. -Remove deletes the container and
keeps both folders.

.PARAMETER Port
The port on 127.0.0.1. Default 3077, where SolidSeas looks; for another, set
SOLIDSEAS_TRACEFINITY_URL to http://127.0.0.1:<port> in the MCP client's settings.
To run Tracefinity on a server instead, see scripts\tracefinity-server.ps1.

.PARAMETER Image
The Tracefinity image. Default the release SolidSeas was checked with.

.PARAMETER Remove
Delete the container (the folders stay).

.EXAMPLE
scripts\tracefinity.ps1
#>
param(
    [int]$Port = 3077,
    [string]$Image = 'ghcr.io/tracefinity/tracefinity:0.10.0',
    [switch]$Remove
)

# Native commands report through their exit codes: Windows PowerShell 5.1 turns their
# standard error into errors that 'Stop' would throw on.
$ErrorActionPreference = 'Continue'
$name = 'tracefinity'
$root = Join-Path $env:LOCALAPPDATA 'SolidSeas\tracefinity'
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker is not installed: install Docker Desktop first (docs/GRIDFINITY.md).'
}
$null = & docker info --format '{{.ServerVersion}}' 2>&1
if ($LASTEXITCODE -ne 0) { throw 'Docker is not running: start Docker Desktop, then run this again.' }
$status = & docker ps -a --filter "name=^/$name$" --format '{{.Status}}' 2>&1
if ($LASTEXITCODE -ne 0) { throw "docker ps failed: $status" }

if ($Remove) {
    if ($status) {
        $null = & docker rm -f $name 2>&1
        "Removed the $name container. Its library and models stay in $root."
    } else {
        "There is no $name container."
    }
    return
}

if (-not $status) {
    New-Item -ItemType Directory -Force (Join-Path $root 'storage'), (Join-Path $root 'models') | Out-Null
    $made = & docker run -d --name $name --restart unless-stopped `
        -p "127.0.0.1:${Port}:3000" `
        -v "$(Join-Path $root 'storage'):/app/storage" `
        -v "$(Join-Path $root 'models'):/app/.u2net" `
        -e AUTH_MODE=open -e NEXT_TELEMETRY_DISABLED=1 `
        $Image 2>&1
    if ($LASTEXITCODE -ne 0) { throw "docker run failed: $made" }
} elseif ($status -notlike 'Up*') {
    $started = & docker start $name 2>&1
    if ($LASTEXITCODE -ne 0) { throw "docker start failed: $started" }
}

# Tracefinity's API answers some seconds after the container starts.
$deadline = (Get-Date).AddMinutes(2)
$version = $null
while (-not $version -and (Get-Date) -lt $deadline) {
    try {
        $version = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/version" -TimeoutSec 5
    } catch {
        Start-Sleep -Seconds 2
    }
}
if (-not $version) { throw "Tracefinity did not answer within two minutes: see docker logs $name." }

# The tracing model (IS-Net, about 170 MB) is fetched here, once, rather than by the first
# trace, which a chat could give up waiting for; once it is in the models folder this only
# checks it.
"Making sure Tracefinity's tracing model is downloaded (about 170 MB the first time)..."
$model = & docker exec -u tracefinity $name python -c "from rembg import new_session; new_session('isnet-general-use')" 2>&1
if ($LASTEXITCODE -ne 0) { Write-Warning "The model was not fetched now, so the first trace will fetch it: $model" }
"Tracefinity $($version.version) is running at http://127.0.0.1:$Port, its library in $root."
