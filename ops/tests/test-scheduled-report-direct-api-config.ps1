Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$scheduledRunner = Join-Path $projectRoot "ops\run-scheduled-project-report.ps1"
$installer = Join-Path $projectRoot "ops\install-report-scheduled-tasks.ps1"

function Assert-True {
    param(
        [Parameter(Mandatory = $true)][bool]$Condition,
        [Parameter(Mandatory = $true)][string]$Message
    )
    if (-not $Condition) {
        throw $Message
    }
}

$runnerText = Get-Content -LiteralPath $scheduledRunner -Raw
$installerText = Get-Content -LiteralPath $installer -Raw

Assert-True ($runnerText -match '\[string\]\$OutputDir') "Scheduled runner should expose OutputDir."
Assert-True ($runnerText -match 'Get-DefaultReportOutputDir') "Scheduled runner should expose a default report folder helper."
Assert-True ($runnerText -match 'D:\\Mira Manager Reports') "Scheduled runner should default to the D drive report folder."
Assert-True ($runnerText -match '\$reportArgs\.DirectApi = \$true') "Scheduled runner should use direct GPT token API by default."
Assert-True (-not ($runnerText -match '(?m)^\s*ForceFallback\s*=\s*\$true')) "Scheduled runner must not hard-code ForceFallback in reportArgs."
Assert-True ($runnerText -match 'if \(\$ForceFallback\)') "Scheduled runner should only use ForceFallback when explicitly requested."
Assert-True ($runnerText -match 'New-ReportFolderShortcut') "Scheduled runner should create/update the desktop report folder shortcut."

Assert-True ($installerText -match '\[string\]\$OutputDir') "Installer should expose OutputDir."
Assert-True ($installerText -match 'D:\\Mira Manager Reports') "Installer should default to the D drive report folder."
Assert-True ($installerText -match '-OutputDir') "Scheduled task action should pass OutputDir."
Assert-True (-not ($installerText -match '-ForceFallback')) "Installed daily/weekly tasks should not force fallback."

Write-Output "[OK] scheduled report direct API config test passed"
