<#
.SYNOPSIS
Run Tracefinity on a Linux server with Docker (an Unraid box, for one) for SolidSeas'
Gridfinity tools, reached from this PC through an SSH tunnel.

.DESCRIPTION
Run it once from this PC. It:

1. makes an SSH key for the tunnel, %USERPROFILE%\.ssh\solidseas_tracefinity, unless it is
   there. The key has no passphrase, so SolidSeas can open the tunnel by itself, and the
   server lets it do that and nothing else: the line it is given in authorized_keys allows one
   forward, to Tracefinity's port on the server's own 127.0.0.1, and no shell or command;
2. signs in to the server with ssh as you (ssh asks for the server's password; only you
   type it), and there adds that line to the user's authorized_keys (on Unraid also to
   /boot/config/ssh/<user>.pubkeys, which Unraid restores at boot), then starts Tracefinity in
   Docker: published on the server's 127.0.0.1 only, AUTH_MODE=open (one library, no
   sign-in, safe because nothing but the server reaches it), its library and tracing model in
   <AppData>/tracefinity owned by <Owner>, started again with Docker; and fetches the model;
3. opens the tunnel once with the new key and checks Tracefinity answers through it.

Then set SOLIDSEAS_TRACEFINITY_SSH to the server (as -Server) in the MCP client's settings
for SolidSeas; docs/GRIDFINITY.md shows where. Run the script again to start a stopped
container; it does not add the key twice.

.PARAMETER Server
The server as ssh takes it: host or user@host, such as root@nas.

.PARAMETER Port
Tracefinity's port, on the server's 127.0.0.1 and on this PC's end of the tunnel alike.

.PARAMETER AppData
The server's folder for container data (Unraid: /mnt/user/appdata).

.PARAMETER Owner
Who owns the data on the server, uid:gid (Unraid: 99:100, nobody:users).

.PARAMETER Image
The Tracefinity image. Default the release SolidSeas was checked with.

.EXAMPLE
scripts\tracefinity-server.ps1 -Server root@nas
#>
param(
    [Parameter(Mandatory = $true)][string]$Server,
    [int]$Port = 3077,
    [string]$AppData = '/mnt/user/appdata',
    [string]$Owner = '99:100',
    [string]$Image = 'ghcr.io/tracefinity/tracefinity:0.10.0'
)

# Native commands report through their exit codes: Windows PowerShell 5.1 turns their
# standard error into errors that 'Stop' would throw on.
$ErrorActionPreference = 'Continue'
if ($Server -notmatch '^([A-Za-z0-9_][A-Za-z0-9._-]{0,31}@)?[A-Za-z0-9][A-Za-z0-9.-]{0,252}$') {
    throw "-Server is a host or user@host, such as root@nas."
}
if ($AppData -notmatch '^/[A-Za-z0-9._/-]+$' -or $Owner -notmatch '^[0-9]+:[0-9]+$' -or $Image -notmatch '^[A-Za-z0-9._/:@-]+$') {
    throw '-AppData, -Owner or -Image holds characters this script does not pass on.'
}
foreach ($tool in 'ssh', 'ssh-keygen') {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw "$tool is missing: add Windows' OpenSSH Client (Settings, Apps, Optional features)."
    }
}
$user = if ($Server -match '@') { $Server.Split('@')[0] } else { $env:USERNAME.ToLowerInvariant() }

# 1. The tunnel's key.
$key = Join-Path $env:USERPROFILE '.ssh\solidseas_tracefinity'
if (-not (Test-Path -LiteralPath $key)) {
    New-Item -ItemType Directory -Force (Split-Path $key) | Out-Null
    # Through cmd so the empty passphrase reaches ssh-keygen in every PowerShell.
    & cmd.exe /c "ssh-keygen -q -t ed25519 -N `"`" -C solidseas-tracefinity -f `"$key`""
    if ($LASTEXITCODE -ne 0) { throw 'ssh-keygen could not make the key.' }
    "Made the tunnel's key $key."
}
$public = (Get-Content -LiteralPath "$key.pub" -Raw).Trim()
if ($public -notmatch '^ssh-ed25519 [A-Za-z0-9+/=]+ [A-Za-z0-9._-]+$') { throw "$key.pub is not the key this script makes." }
$keyline = "restrict,port-forwarding,permitopen=`"127.0.0.1:$Port`",command=`"/bin/false`" $public"

# 2. The server. The script goes as base64 so no quoting or line endings get in its way.
$remote = @'
set -e
port=__PORT__
appdata='__APPDATA__'
owner='__OWNER__'
image='__IMAGE__'
user='__USER__'
keyline='__KEYLINE__'
mkdir -p ~/.ssh && chmod 700 ~/.ssh
touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys
grep -qxF "$keyline" ~/.ssh/authorized_keys || printf '%s\n' "$keyline" >> ~/.ssh/authorized_keys
if [ -d /boot/config/ssh ]; then
  touch "/boot/config/ssh/$user.pubkeys"
  grep -qxF "$keyline" "/boot/config/ssh/$user.pubkeys" || printf '%s\n' "$keyline" >> "/boot/config/ssh/$user.pubkeys"
fi
echo "The tunnel key may forward to 127.0.0.1:$port only."
dir="$appdata/tracefinity"
mkdir -p "$dir/storage" "$dir/models"
chown -R "$owner" "$dir"
if docker ps -a --format '{{.Names}}' | grep -qx tracefinity; then
  docker start tracefinity >/dev/null
  echo "Started the tracefinity container."
else
  echo "Downloading Tracefinity's image (about 3.5 GB the first time)..."
  docker pull "$image"
  docker run -d --name tracefinity --restart unless-stopped \
    -p "127.0.0.1:$port:3000" \
    -v "$dir/storage:/app/storage" -v "$dir/models:/app/.u2net" \
    -e AUTH_MODE=open -e NEXT_TELEMETRY_DISABLED=1 \
    -e PUID="${owner%%:*}" -e PGID="${owner##*:}" \
    "$image" >/dev/null
  echo "Made the tracefinity container, on 127.0.0.1:$port of this server only."
fi
for i in $(seq 1 90); do
  if curl -sf "http://127.0.0.1:$port/api/version" >/dev/null; then break; fi
  sleep 2
done
curl -sf "http://127.0.0.1:$port/api/version" >/dev/null || { echo "Tracefinity did not answer: see docker logs tracefinity"; exit 1; }
echo "Making sure the tracing model is downloaded (about 170 MB the first time)..."
docker exec -u tracefinity tracefinity python -c "from rembg import new_session; new_session('isnet-general-use')" >/dev/null
echo "Tracefinity is running on $(hostname)."
exit 0
'@
$remote = $remote.Replace('__PORT__', "$Port").Replace('__APPDATA__', $AppData).Replace('__OWNER__', $Owner)
$remote = $remote.Replace('__IMAGE__', $Image).Replace('__USER__', $user).Replace('__KEYLINE__', $keyline)
$remote = $remote -replace "`r`n", "`n"
$encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($remote))
"Signing in to $Server to set Tracefinity up there. ssh asks for the password of $Server."
& ssh -o StrictHostKeyChecking=accept-new $Server "echo $encoded | base64 -d | bash"
if ($LASTEXITCODE -ne 0) { throw "The setup on $Server stopped; its messages are above." }

# 3. The tunnel, once, with the new key: what SolidSeas will do by itself.
$forward = "127.0.0.1:${Port}:127.0.0.1:${Port}"
$arguments = @('-N', '-T', '-o', 'BatchMode=yes', '-o', 'ExitOnForwardFailure=yes', '-o', 'ConnectTimeout=10',
    '-i', "`"$key`"", '-o', 'IdentitiesOnly=yes', '-L', $forward, $Server)
$tunnel = Start-Process -FilePath (Get-Command ssh).Source -ArgumentList $arguments -WindowStyle Hidden -PassThru
try {
    $version = $null
    $deadline = (Get-Date).AddSeconds(20)
    while (-not $version -and -not $tunnel.HasExited -and (Get-Date) -lt $deadline) {
        try { $version = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/version" -TimeoutSec 5 } catch { Start-Sleep -Milliseconds 500 }
    }
} finally {
    if (-not $tunnel.HasExited) { Stop-Process -Id $tunnel.Id -Force }
}
if (-not $version) {
    throw "Tracefinity runs on $Server, but the tunnel did not reach it (is port $Port free on this PC, and does $Server allow TCP forwarding?)."
}
"Tracefinity $($version.version) on $Server answers through the tunnel."
''
'In the MCP client''s settings for SolidSeas (docs/GRIDFINITY.md), set:'
"  SOLIDSEAS_TRACEFINITY_SSH = $Server"
if ($Port -ne 3077) { "  SOLIDSEAS_TRACEFINITY_URL = http://127.0.0.1:$Port" }
