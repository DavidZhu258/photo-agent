param(
    [ValidateSet("daily", "weekly")]
    [string]$Mode = "daily",
    [string[]]$Root = @(),
    [string]$Since = "",
    [string]$ProjectRoot = "",
    [string]$PersonalProfilePath = "",
    [string]$OutputDir = "",
    [string]$ReportFolderShortcutName = "Mira Manager Reports.lnk",
    [switch]$ForceFallback,
    [switch]$EnableGitActivity,
    [switch]$DisableFileActivity
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Utf8File {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Content
    )

    $parent = Split-Path -Parent $Path
    if ($parent -and -not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    Set-Content -LiteralPath $Path -Value $Content -Encoding UTF8
}

function Get-DefaultReportOutputDir {
    $envOutput = [Environment]::GetEnvironmentVariable("MANAGER_REPORT_OUTPUT_DIR")
    if ($envOutput -and $envOutput.Trim().Length -gt 0) {
        return $envOutput.Trim()
    }
    if (Test-Path -LiteralPath "D:\") {
        return "D:\Mira Manager Reports"
    }
    return (Join-Path ([Environment]::GetFolderPath("MyDocuments")) "Mira Manager Reports")
}

function New-ReportFolderShortcut {
    param(
        [Parameter(Mandatory = $true)][string]$TargetPath,
        [Parameter(Mandatory = $true)][string]$ShortcutName
    )

    $desktop = [Environment]::GetFolderPath("Desktop")
    if (-not $desktop -or $desktop.Trim().Length -eq 0) {
        $desktop = Join-Path $env:USERPROFILE "Desktop"
    }
    $shortcutPath = Join-Path $desktop $ShortcutName
    try {
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($shortcutPath)
        $shortcut.TargetPath = $TargetPath
        $shortcut.WorkingDirectory = $TargetPath
        $shortcut.Description = "Open Mira manager report folder"
        $shortcut.Save()
        return $shortcutPath
    }
    catch {
        Write-Output "[WARN] Could not create desktop report folder shortcut. $($_.Exception.Message)"
        return ""
    }
}

if (-not $ProjectRoot -or $ProjectRoot.Trim().Length -eq 0) {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}
if (-not $Root -or $Root.Count -eq 0) {
    $Root = @($ProjectRoot)
}

if (-not (Test-Path -LiteralPath $ProjectRoot)) {
    throw "Project root not found: $ProjectRoot"
}

$reportScript = Join-Path $ProjectRoot "ops\run-project-report.ps1"
if (-not (Test-Path -LiteralPath $reportScript)) {
    throw "Report script not found: $reportScript"
}

if (-not $Since -or $Since.Trim().Length -eq 0) {
    if ($Mode -eq "weekly") {
        $Since = "7 days ago"
    }
    else {
        $Since = "yesterday"
    }
}

if (-not $OutputDir -or $OutputDir.Trim().Length -eq 0) {
    $OutputDir = Get-DefaultReportOutputDir
}
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
$reportShortcutPath = New-ReportFolderShortcut -TargetPath $OutputDir -ShortcutName $ReportFolderShortcutName

$logDir = Join-Path $ProjectRoot "logs\scheduled-reports"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logPath = Join-Path $logDir "$stamp-$Mode.log"

$header = @"
[i] Scheduled project report
[i] Mode: $Mode
[i] Root: $($Root -join ", ")
[i] Since: $Since
[i] ProjectRoot: $ProjectRoot
[i] OutputDir: $OutputDir
[i] ReportFolderShortcut: $reportShortcutPath
[i] Started: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
"@
Write-Utf8File -Path $logPath -Content $header

try {
    Push-Location -LiteralPath $ProjectRoot
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $effectiveRoot = @($Root)
        if (($Root.Count -eq 1) -and (($Root[0].TrimEnd("\", "/")) -ieq "E:\python_project")) {
            $candidateRoots = @(
                "E:\python_project\server_try",
                "E:\python_project\alpaca\FinRL-Trading",
                "E:\python_project\vectordbz",
                "E:\python_project\photo_agent"
            )
            $effectiveRoot = @($candidateRoots | Where-Object { Test-Path -LiteralPath $_ })
            Add-Content -LiteralPath $logPath -Encoding UTF8 -Value "[i] Expanded Root for scheduled file scan: $($effectiveRoot -join ", ")"
        }
        $reportArgs = @{
            Mode = $Mode
            Root = $effectiveRoot
            Since = $Since
            PersonalProfilePath = $PersonalProfilePath
            OutputDir = $OutputDir
        }
        if ($ForceFallback) {
            $reportArgs.ForceFallback = $true
        }
        else {
            $reportArgs.DirectApi = $true
        }
        if (-not $EnableGitActivity) {
            $reportArgs.SkipGitActivity = $true
        }
        if (-not $DisableFileActivity) {
            $reportArgs.IncludeFileActivity = $true
        }
        Add-Content -LiteralPath $logPath -Encoding UTF8 -Value "[i] Invoking report script: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")"
        $ErrorActionPreference = "Continue"
        & $reportScript @reportArgs 2>&1 | Tee-Object -FilePath $logPath -Append
        $lastExitCodeVar = Get-Variable -Name LASTEXITCODE -ErrorAction SilentlyContinue
        if ($lastExitCodeVar) {
            $reportExitCode = [int]$lastExitCodeVar.Value
        }
        else {
            $reportExitCode = 0
        }
        $ErrorActionPreference = $previousErrorActionPreference
        Add-Content -LiteralPath $logPath -Encoding UTF8 -Value "[i] Report script returned: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss") exit=$reportExitCode"
        if ($reportExitCode -ne 0) {
            throw "Report script failed with exit code $reportExitCode"
        }
    }
    finally {
        if ($previousErrorActionPreference) {
            $ErrorActionPreference = $previousErrorActionPreference
        }
        Pop-Location
    }
    Add-Content -LiteralPath $logPath -Encoding UTF8 -Value "[OK] Finished: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")"
    exit 0
}
catch {
    Add-Content -LiteralPath $logPath -Encoding UTF8 -Value "[ERROR] $($_.Exception.Message)"
    exit 1
}
