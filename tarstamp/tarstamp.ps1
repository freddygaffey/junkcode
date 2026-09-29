# tarstamp - timestamped tar snapshots (PowerShell)
# https://github.com/freddygaffey/tarstamp

function tarstamp {
    param(
        [Parameter(Mandatory=$true, Position=0)]
        [string]$Path
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        Write-Error "tarstamp: '$Path' does not exist"
        return
    }
    $name = (Get-Item -LiteralPath $Path).Name
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $archive = "${name}_${stamp}.tar"
    $elapsed = Measure-Command { tar cf $archive $Path }
    if ($LASTEXITCODE -ne 0) { Write-Error "tarstamp: tar failed"; return }
    $bytes = (Get-Item -LiteralPath $archive).Length
    $size = switch ($bytes) {
        { $_ -ge 1GB } { "{0:N1}G" -f ($bytes / 1GB); break }
        { $_ -ge 1MB } { "{0:N1}M" -f ($bytes / 1MB); break }
        { $_ -ge 1KB } { "{0:N1}K" -f ($bytes / 1KB); break }
        default        { "${bytes}B" }
    }
    $secs = "{0:N1}" -f $elapsed.TotalSeconds
    Write-Host "-> $archive | ${secs}s | $size"
}

function untarstamp {
    param(
        [Parameter(Mandatory=$true, Position=0)]
        [string]$Archive
    )
    if (-not (Test-Path -LiteralPath $Archive)) {
        Write-Error "untarstamp: '$Archive' not found"
        return
    }
    $base = [System.IO.Path]::GetFileNameWithoutExtension($Archive)
    $dest = Join-Path (Split-Path -Parent (Resolve-Path $Archive)) "$base.extracted"
    New-Item -ItemType Directory -Path $dest -Force | Out-Null
    tar xf $Archive -C $dest
    if ($LASTEXITCODE -eq 0) { Write-Host "-> $dest" }
}
