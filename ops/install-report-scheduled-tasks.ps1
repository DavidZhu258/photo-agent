param(
    [string]$ProjectRoot = "",
    [string[]]$ScanRoot = @(),
    [string]$PersonalProfilePath = "",
    [string]$OutputDir = "",
    [string]$DailyTime = "18:30",
    [string]$WeeklyTime = "18:45"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Quote-Arg {
    param([Parameter(Mandatory = $true)][string]$Value)
    return ('"{0}"' -f ($Value.Replace('"', '\"')))
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

if (-not $ProjectRoot -or $ProjectRoot.Trim().Length -eq 0) {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}
if (-not $ScanRoot -or $ScanRoot.Count -eq 0) {
    $ScanRoot = @($ProjectRoot)
}
if (-not $OutputDir -or $OutputDir.Trim().Length -eq 0) {
    $OutputDir = Get-DefaultReportOutputDir
}

if (-not (Test-IsAdmin)) {
    $scriptPath = $MyInvocation.MyCommand.Path
    $argList = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", (Quote-Arg $scriptPath),
        "-ProjectRoot", (Quote-Arg $ProjectRoot),
        "-ScanRoot", (($ScanRoot | ForEach-Object { Quote-Arg $_ }) -join " "),
        "-PersonalProfilePath", (Quote-Arg $PersonalProfilePath),
        "-OutputDir", (Quote-Arg $OutputDir),
        "-DailyTime", (Quote-Arg $DailyTime),
        "-WeeklyTime", (Quote-Arg $WeeklyTime)
    ) -join " "

    Write-Output "[i] Administrator permission is required to register Windows scheduled tasks."
    Write-Output "[i] Launching elevated PowerShell..."
    Start-Process -FilePath "powershell.exe" -ArgumentList $argList -Verb RunAs
    exit 0
}

if (-not (Test-Path -LiteralPath $ProjectRoot)) {
    throw "Project root not found: $ProjectRoot"
}

$runner = Join-Path $ProjectRoot "ops\run-scheduled-project-report.ps1"
if (-not (Test-Path -LiteralPath $runner)) {
    throw "Scheduled runner not found: $runner"
}

$dailyName = "Mira Project Daily Manager Report"
$weeklyName = "Mira Project Weekly Manager Report"
$pwshCommand = Get-Command pwsh.exe -ErrorAction SilentlyContinue
if ($pwshCommand) {
    $powershell = $pwshCommand.Source
}
else {
    $powershell = (Get-Command powershell.exe).Source
}

$scanRootArgs = (($ScanRoot | ForEach-Object { "`"$_`"" }) -join " ")
$dailyArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$runner`" -Mode daily -Root $scanRootArgs -Since `"yesterday`" -ProjectRoot `"$ProjectRoot`" -PersonalProfilePath `"$PersonalProfilePath`" -OutputDir `"$OutputDir`""
$weeklyArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$runner`" -Mode weekly -Root $scanRootArgs -Since `"7 days ago`" -ProjectRoot `"$ProjectRoot`" -PersonalProfilePath `"$PersonalProfilePath`" -OutputDir `"$OutputDir`""

$dailyAction = New-ScheduledTaskAction -Execute $powershell -Argument $dailyArgs -WorkingDirectory $ProjectRoot
$weeklyAction = New-ScheduledTaskAction -Execute $powershell -Argument $weeklyArgs -WorkingDirectory $ProjectRoot
$dailyTrigger = New-ScheduledTaskTrigger -Daily -At $DailyTime
$weeklyTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday -At $WeeklyTime
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $dailyName -Action $dailyAction -Trigger $dailyTrigger -Settings $settings -Principal $principal -Description "Generate daily Chinese manager report from file-date activity with personal growth reminders; git activity can be enabled manually." -Force | Out-Null
Register-ScheduledTask -TaskName $weeklyName -Action $weeklyAction -Trigger $weeklyTrigger -Settings $settings -Principal $principal -Description "Generate weekly Chinese manager report from file-date activity with personal growth reminders; git activity can be enabled manually." -Force | Out-Null

Write-Output "[OK] Registered scheduled task: $dailyName at $DailyTime daily"
Write-Output "[OK] Registered scheduled task: $weeklyName at $WeeklyTime every Friday"
Get-ScheduledTask -TaskName $dailyName, $weeklyName | Select-Object TaskName, State
