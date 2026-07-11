<#
.SYNOPSIS
    Install every toolkit skill user-level: skills/<name> -> %USERPROFILE%\.claude\skills\<name>.
.DESCRIPTION
    Mirrors each skill directory with robocopy /MIR so updates AND deletions propagate.
    Idempotent -- safe to re-run after every `git pull`. Claude Code auto-discovers
    user-level skills in every repo; no per-repo copying needed.
    Windows PowerShell 5.1 compatible.
.EXAMPLE
    .\install.ps1            # install / update all skills
.EXAMPLE
    .\install.ps1 -WhatIf    # preview: prints what would be mirrored, copies nothing
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param()

$ErrorActionPreference = 'Stop'

$src = Join-Path $PSScriptRoot 'skills'
$dstRoot = Join-Path $env:USERPROFILE '.claude\skills'

if (-not (Test-Path $src)) {
    Write-Error "skills/ not found next to install.ps1 (expected $src). Run from a full clone."
    exit 1
}

$skills = @(Get-ChildItem -Path $src -Directory)
if ($skills.Count -eq 0) {
    Write-Error "No skill directories under $src."
    exit 1
}

if (-not (Test-Path $dstRoot)) {
    if ($PSCmdlet.ShouldProcess($dstRoot, 'Create directory')) {
        New-Item -ItemType Directory -Path $dstRoot -Force | Out-Null
    }
}

$installed = @()
$failed = @()
foreach ($skill in $skills) {
    $dst = Join-Path $dstRoot $skill.Name
    if ($PSCmdlet.ShouldProcess($dst, "Mirror skill '$($skill.Name)' (robocopy /MIR)")) {
        # /MIR propagates renames and deletions from the repo; caches excluded.
        # robocopy exit codes 0-7 = success, >=8 = failure.
        robocopy $skill.FullName $dst /MIR /XD __pycache__ .git /XF *.pyc /NFL /NDL /NJH /NJS /NP | Out-Null
        if ($LASTEXITCODE -ge 8) {
            $failed += $skill.Name
            Write-Warning "robocopy failed for '$($skill.Name)' (exit $LASTEXITCODE)."
        }
        else {
            $installed += $skill.Name
        }
    }
}

if ($installed.Count -gt 0) {
    Write-Host "Installed/updated $($installed.Count) skill(s) -> $dstRoot"
    foreach ($name in $installed) { Write-Host "  $name" }
    Write-Host "Claude Code picks these up in every repo on next session start."
}
if ($failed.Count -gt 0) {
    Write-Error ("Failed: " + ($failed -join ', '))
    exit 1
}
exit 0
