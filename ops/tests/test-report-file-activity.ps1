Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$scriptPath = Join-Path $projectRoot "ops\run-project-report.ps1"
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("report-file-activity-" + [guid]::NewGuid().ToString("N"))
$outputDir = Join-Path $tempRoot "reports"
$scanRoot = Join-Path $tempRoot "scan-root"
$profilePath = Join-Path $tempRoot "profile.md"

function Assert-True {
    param(
        [Parameter(Mandatory = $true)][bool]$Condition,
        [Parameter(Mandatory = $true)][string]$Message
    )
    if (-not $Condition) {
        throw $Message
    }
}

try {
    New-Item -ItemType Directory -Path $scanRoot -Force | Out-Null
    $workFile = Join-Path $scanRoot "today-work.md"
    Set-Content -LiteralPath $workFile -Encoding UTF8 -Value "# Today`nCustomer-facing AI portfolio work."
    Set-Content -LiteralPath $profilePath -Encoding UTF8 -Value "# Personal Profile`nNeed reminders on customer impact, compliance, English demos."

    & $scriptPath `
        -Mode daily `
        -Root @($scanRoot) `
        -Since "today" `
        -OutputDir $outputDir `
        -Label "file-activity-test" `
        -RawOnly `
        -SkipGitActivity `
        -IncludeFileActivity `
        -PersonalProfilePath $profilePath | Out-Null

    $rawPath = Join-Path $outputDir ((Get-Date -Format "yyyy-MM-dd") + "-file-activity-test-daily.activity.json")
    Assert-True (Test-Path -LiteralPath $rawPath) "Expected activity JSON was not created: $rawPath"

    $raw = Get-Content -LiteralPath $rawPath -Raw | ConvertFrom-Json -Depth 100
    Assert-True ($raw.PSObject.Properties.Name -contains "file_activity") "Missing file_activity in raw activity JSON."
    Assert-True ($raw.file_activity.roots.Count -eq 1) "Expected one file activity root."
    Assert-True ($raw.file_activity.roots[0].files.Count -eq 1) "Expected one changed file in file activity."
    Assert-True ($raw.file_activity.roots[0].files[0].path -like "*today-work.md") "Changed file path was not captured."
    Assert-True ($raw.PSObject.Properties.Name -contains "personal_profile") "Missing personal_profile in raw activity JSON."
    Assert-True ($raw.personal_profile.available -eq $true) "Expected personal_profile.available to be true."
    Assert-True ($raw.personal_profile.content -like "*customer impact*") "Personal profile content was not captured."

    Write-Output "[OK] report file activity test passed"
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}
