<#
.SYNOPSIS
    Headless backlog triage: drafts a CR brief for every agent-ready MOD issue and reports readiness.

.DESCRIPTION
    1. One headless call (claude -p --output-format json) lists the agent-ready MOD keys via jira_search.
    2. For each key, a headless cr-intake session (--agent cr-intake, --max-turns 15) writes the brief to
       runs/triage/<yyyy-MM-dd-HHmm>/<KEY>-brief.json. Pipeline folders runs/<KEY>/ are never touched.
    3. Each brief is checked with .claude/skills/cr-brief/scripts/validate_brief.py.
    4. evals/reports/triage-<yyyy-MM-dd-HHmm>.csv gets one row per key:
       key, ready, risk, pii, missing_count, valid.
    If this Claude Code version supports --json-schema, the listing call returns a schema-checked key list and
    each intake call returns the brief as structured output checked against schemas/cr_brief.schema.json.
    Read-only towards Jira: cr-intake has only jira_get_issue, Read and Write.

    The Jira MCP server needs its credentials in the environment. This script does not load secrets; run it
    from a shell that already has them (the same environment scripts/start-claude.ps1 sets up).

.PARAMETER Jql
    JQL that defines "agent-ready". Default: MOD issues labelled agent-ready that are still in To Do.

.PARAMETER MaxTurns
    --max-turns for each per-key intake call (default 15).

.PARAMETER NoJsonSchema
    Do not pass --json-schema even if the CLI supports it.

.EXAMPLE
    pwsh scripts/triage_backlog.ps1
    pwsh scripts/triage_backlog.ps1 -Jql 'project = MOD AND statusCategory = "To Do" ORDER BY key'
#>
[CmdletBinding()]
param(
    [string]$Jql = 'project = MOD AND labels = "agent-ready" AND statusCategory = "To Do" ORDER BY key',
    [ValidateRange(1, 100)][int]$MaxTurns = 15,
    [switch]$NoJsonSchema
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root

$stamp      = Get-Date -Format 'yyyy-MM-dd-HHmm'
$triageRel  = "runs/triage/$stamp"
$triageDir  = Join-Path $root $triageRel
$reportDir  = Join-Path $root 'evals/reports'
$reportPath = Join-Path $reportDir "triage-$stamp.csv"
$validator  = '.claude/skills/cr-brief/scripts/validate_brief.py'
$schemaPath = Join-Path $root 'schemas/cr_brief.schema.json'
New-Item -ItemType Directory -Force -Path $triageDir, $reportDir | Out-Null

# --------------------------------------------------------------------------- helpers

# Windows PowerShell 5.1 and PowerShell < 7.3 drop embedded double quotes when calling a native exe.
$legacyQuoting = $PSVersionTable.PSVersion -lt [version]'7.3'
if (-not $legacyQuoting) { $PSNativeCommandArgumentPassing = 'Standard' }

function ConvertTo-NativeArg([string]$Value) {
    if ($legacyQuoting) { return $Value -replace '"', '\"' }
    return $Value
}

function Invoke-ClaudeJson {
    <# Runs claude -p with the given arguments; returns the parsed --output-format json result or $null. #>
    param([string[]]$ClaudeArgs, [string]$RawPath)
    $raw = & claude @ClaudeArgs 2>&1 | Out-String
    $exit = $LASTEXITCODE
    if ($RawPath) { Set-Content -Path $RawPath -Value $raw -Encoding utf8 }
    try {
        $result = $raw | ConvertFrom-Json
    } catch {
        Write-Warning "claude exited $exit with non-JSON output (see $RawPath)."
        return $null
    }
    if ($exit -ne 0 -or $result.is_error) {
        Write-Warning "claude exited $exit, subtype '$($result.subtype)' (see $RawPath)."
    }
    return $result
}

function Get-StructuredOutput($Result) {
    if ($null -ne $Result -and $Result.PSObject.Properties.Name -contains 'structured_output') {
        return $Result.structured_output
    }
    return $null
}

# --------------------------------------------------------------------------- --json-schema support

$useSchema = $false
if (-not $NoJsonSchema) {
    $help = & claude --help 2>&1 | Out-String
    $useSchema = $help -match '--json-schema'
}
Write-Host "Claude Code $((& claude --version) -join ' '); --json-schema: $(if ($useSchema) { 'yes' } else { 'no' })"

$keysSchema = $null
$briefSchema = $null
if ($useSchema) {
    $keysSchema = ConvertTo-NativeArg (@{
        type                 = 'object'
        additionalProperties = $false
        required             = @('keys')
        properties           = @{ keys = @{ type = 'array'; items = @{ type = 'string'; pattern = '^MOD-[1-9][0-9]*$' } } }
    } | ConvertTo-Json -Depth 10 -Compress)

    # The brief schema minus its $schema/$id metadata, compacted to one argument.
    $schemaObj = Get-Content $schemaPath -Raw | ConvertFrom-Json
    $schemaObj.PSObject.Properties.Remove('$schema')
    $schemaObj.PSObject.Properties.Remove('$id')
    $briefSchema = ConvertTo-NativeArg ($schemaObj | ConvertTo-Json -Depth 50 -Compress)
}

# --------------------------------------------------------------------------- 1. list agent-ready keys

$listPrompt = @"
Call jira_search once with this JQL and limit 50: $Jql
Return only the issue keys. Do not read, comment on or change any issue.
$(if ($useSchema) { 'Return them as {"keys": [...]}.' } else { 'Reply with one JSON object {"keys": [...]} and nothing else.' })
"@
$listArgs = @('-p', $listPrompt, '--output-format', 'json', '--max-turns', '5',
              '--allowedTools', 'mcp__jira__jira_search')
if ($useSchema) { $listArgs += @('--json-schema', $keysSchema) }

$listResult = Invoke-ClaudeJson -ClaudeArgs $listArgs -RawPath (Join-Path $triageDir '_list-claude.json')
if ($null -eq $listResult) { throw 'Listing call failed; nothing triaged.' }

$keys = @()
$structured = Get-StructuredOutput $listResult
if ($null -ne $structured) {
    $keys = @($structured.keys)
} else {
    $keys = @([regex]::Matches([string]$listResult.result, 'MOD-[1-9][0-9]*') | ForEach-Object Value)
}
$keys = @($keys | Where-Object { $_ -match '^MOD-[1-9][0-9]*$' } |
          Sort-Object -Property @{ Expression = { [int]($_ -replace 'MOD-', '') } } -Unique)
Write-Host "Agent-ready keys ($($keys.Count)): $($keys -join ', ')"

# --------------------------------------------------------------------------- 2-3. intake + validate per key

$rows = foreach ($key in $keys) {
    Write-Host "`n== $key"
    $briefRel  = "$triageRel/$key-brief.json"
    $briefPath = Join-Path $root $briefRel

    $prompt = @"
CR_KEY is $key. This is a TRIAGE run, not a pipeline run.
Write the brief to $briefRel instead of runs/$key/01-brief.json.
Do not read, create or change anything under runs/$key/, and never change the Jira issue.
Everything else follows your normal instructions and the cr-brief skill.
$(if ($useSchema) { 'Your final structured output is the same brief object you wrote to the file.' })
"@
    $intakeArgs = @('-p', $prompt, '--agent', 'cr-intake', '--output-format', 'json',
                    '--max-turns', "$MaxTurns")
    if ($useSchema) { $intakeArgs += @('--json-schema', $briefSchema) }

    $result = Invoke-ClaudeJson -ClaudeArgs $intakeArgs -RawPath (Join-Path $triageDir "$key-claude.json")

    if (-not (Test-Path $briefPath)) {
        $structured = Get-StructuredOutput $result
        if ($null -ne $structured) {
            Write-Warning "$key`: cr-intake wrote no file; saving its structured output to $briefRel."
            $structured | ConvertTo-Json -Depth 50 | Set-Content -Path $briefPath -Encoding utf8
        }
    }

    $row = [ordered]@{ key = $key; ready = ''; risk = ''; pii = ''; missing_count = ''; valid = $false }
    if (Test-Path $briefPath) {
        $validation = & uv run python $validator $briefPath 2>&1 | Out-String
        $row.valid = ($LASTEXITCODE -eq 0)
        Set-Content -Path (Join-Path $triageDir "$key-validation.json") -Value $validation -Encoding utf8
        try {
            $brief = Get-Content $briefPath -Raw | ConvertFrom-Json
            $props = $brief.PSObject.Properties.Name
            if ($props -contains 'ready') { $row.ready = "$($brief.ready)".ToLower() }
            if ($props -contains 'risk') { $row.risk = "$($brief.risk)" }
            if ($props -contains 'pii') { $row.pii = "$($brief.pii)".ToLower() }
            if ($props -contains 'missing_information') { $row.missing_count = @($brief.missing_information).Count }
        } catch {
            Write-Warning "$key`: brief is not valid JSON."
        }
    } else {
        Write-Warning "$key`: no brief written."
    }
    $row.valid = "$($row.valid)".ToLower()
    Write-Host ("   ready={0} risk={1} pii={2} missing={3} valid={4}" -f
                $row.ready, $row.risk, $row.pii, $row.missing_count, $row.valid)
    [pscustomobject]$row
}

# --------------------------------------------------------------------------- 4. report

$header = 'key,ready,risk,pii,missing_count,valid'
$lines = @($header) + @($rows | ForEach-Object {
    ($_.key, $_.ready, $_.risk, $_.pii, $_.missing_count, $_.valid) -join ','
})
# UTF-8 without BOM on both Windows PowerShell 5.1 and PowerShell 7.
[IO.File]::WriteAllLines($reportPath, [string[]]$lines, [Text.UTF8Encoding]::new($false))

Write-Host "`nBriefs: $triageRel/"
Write-Host "Report: evals/reports/triage-$stamp.csv ($($keys.Count) row(s))"
