# Loads .env into this session only, then starts Claude Code in the repo root
$root = Resolve-Path (Join-Path $PSScriptRoot '..')
Get-Content (Join-Path $root '.env') | Where-Object { $_ -match '^\s*[^#].*=' } | ForEach-Object {
    $name, $value = $_ -split '=', 2
    [Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim(), 'Process')
}
Set-Location $root
claude @args
