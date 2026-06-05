param(
    [ValidateSet("daily", "weekly")]
    [string]$Mode = "daily",
    [string[]]$Root = @(),
    [string]$Since = "",
    [string]$Until = "",
    [string]$OutputDir = "",
    [string]$Label = "",
    [string]$Model = "gpt-5.5",
    [string]$ApiBase = "https://zzshu.cc/v1",
    [switch]$DirectApi,
    [switch]$RawOnly,
    [switch]$IncludeFileActivity,
    [switch]$SkipGitActivity,
    [switch]$ForceFallback,
    [string]$PersonalProfilePath = "",
    [int]$MaxFilesPerRoot = 80
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

function Get-ProjectRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

function Get-DefaultReportOutputDir {
    $envOutput = [Environment]::GetEnvironmentVariable("MANAGER_REPORT_OUTPUT_DIR")
    if ($envOutput -and $envOutput.Trim().Length -gt 0) {
        return $envOutput.Trim()
    }
    if (Test-Path -LiteralPath "D:\") {
        return "D:\Mira Manager Reports"
    }
    return (Join-Path (Get-ProjectRoot) "reports")
}

function Resolve-SinceDate {
    param(
        [Parameter(Mandatory = $true)][string]$ReportMode,
        [string]$SinceValue = ""
    )

    if (-not $SinceValue -or $SinceValue.Trim().Length -eq 0) {
        if ($ReportMode -eq "weekly") {
            return (Get-Date).Date.AddDays(-7)
        }
        return (Get-Date).Date.AddDays(-1)
    }

    $normalized = $SinceValue.Trim().ToLowerInvariant()
    if ($normalized -eq "today") {
        return (Get-Date).Date
    }
    if ($normalized -eq "yesterday") {
        return (Get-Date).Date.AddDays(-1)
    }
    if ($normalized -eq "7 days ago") {
        return (Get-Date).Date.AddDays(-7)
    }

    $parsed = [datetime]::MinValue
    if ([datetime]::TryParse($SinceValue, [ref]$parsed)) {
        return $parsed
    }

    if ($ReportMode -eq "weekly") {
        return (Get-Date).Date.AddDays(-7)
    }
    return (Get-Date).Date.AddDays(-1)
}

function Test-IsIgnoredReportPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    $patterns = @(
        "\\\.git\\",
        "\\node_modules\\",
        "\\\.next\\",
        "\\__pycache__\\",
        "\\\.venv\\",
        "\\venv\\",
        "\\dist\\",
        "\\build\\",
        "\\\.dart_tool\\",
        "\\\.gradle\\",
        "\\coverage\\",
        "\\logs\\",
        "\\reports\\",
        "\\target\\"
    )
    foreach ($pattern in $patterns) {
        if ($Path -match $pattern) {
            return $true
        }
    }
    return $false
}

function Get-FileActivity {
    param(
        [Parameter(Mandatory = $true)][string[]]$RootPaths,
        [Parameter(Mandatory = $true)][datetime]$SinceDate,
        [Parameter(Mandatory = $true)][int]$MaxFiles
    )

    $rootActivities = @()
    foreach ($rootPath in $RootPaths) {
        $rootPath = [string]$rootPath
        Write-Host "[i] Scanning file activity for $rootPath since '$($SinceDate.ToString("yyyy-MM-dd HH:mm:ss"))'"
        $files = New-Object System.Collections.ArrayList
        if (Test-Path -LiteralPath $rootPath) {
            $pending = New-Object System.Collections.Stack
            $pending.Push($rootPath)
            while (($pending.Count -gt 0) -and ($files.Count -lt $MaxFiles)) {
                $current = $pending.Pop()
                if (Test-IsIgnoredReportPath -Path ($current.TrimEnd("\") + "\")) {
                    continue
                }
                try {
                    foreach ($filePath in [System.IO.Directory]::EnumerateFiles($current)) {
                        if ($files.Count -ge $MaxFiles) {
                            break
                        }
                        if (Test-IsIgnoredReportPath -Path $filePath) {
                            continue
                        }
                        try {
                            $item = Get-Item -LiteralPath $filePath -Force -ErrorAction Stop
                            if ($item.LastWriteTime -ge $SinceDate) {
                                $files.Add([pscustomobject]@{
                                    path = $item.FullName
                                    last_write_time = $item.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
                                    bytes = $item.Length
                                }) | Out-Null
                            }
                        }
                        catch {
                        }
                    }
                    foreach ($dirPath in [System.IO.Directory]::EnumerateDirectories($current)) {
                        if (-not (Test-IsIgnoredReportPath -Path ($dirPath.TrimEnd("\") + "\"))) {
                            $pending.Push($dirPath)
                        }
                    }
                }
                catch {
                }
            }
        }

        $rootActivities += [pscustomobject]@{
            root = $rootPath
            label = (Get-SafeLabel -RootPath $rootPath)
            since = $SinceDate.ToString("yyyy-MM-dd HH:mm:ss")
            changed_file_count = $files.Count
            files = @($files)
        }
    }

    return [pscustomobject]@{
        generated_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
        roots = $rootActivities
    }
}

function Get-PersonalProfile {
    param([string]$Path = "")

    if ($Path -and (Test-Path -LiteralPath $Path)) {
        $content = Get-Content -LiteralPath $Path -Raw
        return [pscustomobject]@{
            available = $true
            path = $Path
            content = $content
        }
    }

    return [pscustomobject]@{
        available = $false
        path = $Path
        content = ""
    }
}

function New-ActivityJson {
    param(
        [Parameter(Mandatory = $true)][string]$ReportMode,
        [Parameter(Mandatory = $true)][string]$SinceValue,
        [string]$UntilValue = "",
        [object]$GitActivity = $null,
        [object]$FileActivity = $null,
        [object]$PersonalProfile = $null
    )

    $activity = [pscustomobject]@{
        mode = $ReportMode
        since = $SinceValue
        until = $UntilValue
        generated_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
        git_activity = $GitActivity
        file_activity = $FileActivity
        personal_profile = $PersonalProfile
    }
    return ($activity | ConvertTo-Json -Depth 100)
}

function Get-Token {
    $tokenFile = Join-Path $env:USERPROFILE ".codex-gpt55-token\secrets\gpt55-pro.key"
    if ($env:GPT55_PRO_API_KEY -and $env:GPT55_PRO_API_KEY.Trim().Length -gt 0) {
        return $env:GPT55_PRO_API_KEY.Trim()
    }
    if (Test-Path -LiteralPath $tokenFile) {
        return (Get-Content -LiteralPath $tokenFile -Raw).Trim()
    }
    throw "GPT55 token not found. Set GPT55_PRO_API_KEY or create $tokenFile"
}

function Invoke-Glimpse {
    param(
        [Parameter(Mandatory = $true)][string]$GlimpseExe,
        [Parameter(Mandatory = $true)][string]$WorkDir,
        [Parameter(Mandatory = $true)][string]$ReportMode,
        [Parameter(Mandatory = $true)][string]$SinceValue,
        [string]$UntilValue = ""
    )

    $args = @()
    if ($ReportMode -eq "weekly") {
        $args += "week"
    }
    else {
        $args += "standup"
    }
    $args += "--json"
    $args += "--context"
    $args += "both"
    $args += "--skip-setup"
    if ($SinceValue -and $SinceValue.Trim().Length -gt 0) {
        $args += "--since"
        $args += $SinceValue
    }
    if (($ReportMode -eq "weekly") -and $UntilValue -and $UntilValue.Trim().Length -gt 0) {
        $args += "--until"
        $args += $UntilValue
    }

    $previousErrorActionPreference = $ErrorActionPreference
    Push-Location -LiteralPath $WorkDir
    try {
        $ErrorActionPreference = "Continue"
        $output = & $GlimpseExe @args 2>&1
        $glimpseExitCode = $LASTEXITCODE
        $ErrorActionPreference = $previousErrorActionPreference
        if ($glimpseExitCode -ne 0) {
            return ("Error: gitglimpse failed with exit code {0}. {1}" -f $glimpseExitCode, (($output | ForEach-Object { $_.ToString() }) -join "`n"))
        }
    }
    finally {
        if ($previousErrorActionPreference) {
            $ErrorActionPreference = $previousErrorActionPreference
        }
        Pop-Location
    }

    return (($output | ForEach-Object { $_.ToString() }) -join "`n")
}

function Invoke-GptReport {
    param(
        [Parameter(Mandatory = $true)][string]$Token,
        [Parameter(Mandatory = $true)][string]$Endpoint,
        [Parameter(Mandatory = $true)][string]$ModelName,
        [Parameter(Mandatory = $true)][string]$ReportMode,
        [Parameter(Mandatory = $true)][string]$RawJson
    )

    $system = @"
You are a senior engineering lead writing a concise Chinese progress report for a manager.
Use only the provided engineering activity JSON. It may include git activity, file-date activity, and a personal growth profile. Do not invent meetings, tests, releases, or blockers.
Translate technical work into product and engineering impact.
Keep file paths and commit evidence when useful, but do not dump raw diffs.
"@

    if ($ReportMode -eq "weekly") {
        $user = @"
Generate a Chinese weekly engineering report from this engineering activity JSON.

Required structure:
# Weekly Project Report
## One-line Summary
## Main Outcomes
## Important Technical Changes
## Product / User Impact
## Quality, Verification, and Deployment
## Risks / Blockers
## Next Week Focus
## Evidence

Rules:
- Write for a manager, not for a compiler.
- Group by real work themes.
- Mention uncertainty if the git data is insufficient.
- Keep it compact but specific.

gitglimpse JSON:
$RawJson
"@
    }
    else {
        $user = @"
Generate a Chinese daily engineering report from this engineering activity JSON.

Required structure:
# Daily Project Report
## One-line Summary
## Completed Today
## Key Changes
## Product / User Impact
## Quality, Verification, and Deployment
## Risks / Blockers
## Tomorrow Focus
## Evidence

Rules:
- Write for a manager, not for a compiler.
- Group by real work themes.
- Mention uncertainty if the git data is insufficient.
- Keep it compact but specific.

gitglimpse JSON:
$RawJson
"@
    }

    $headers = @{
        Authorization = "Bearer $Token"
        "Content-Type" = "application/json"
    }

    $modelsToTry = @($ModelName)
    if ($ModelName -eq "gpt-5.5") {
        $modelsToTry += "gpt-5.4"
    }

    $lastError = ""
    foreach ($candidateModel in $modelsToTry) {
        $payload = @{
            model = $candidateModel
            messages = @(
                @{ role = "system"; content = $system },
                @{ role = "user"; content = $user }
            )
            temperature = 0.25
        }

        try {
            $json = $payload | ConvertTo-Json -Depth 10
            $responseText = Invoke-RestMethod -Method Post -Uri $Endpoint -Headers $headers -Body $json -TimeoutSec 180
            $content = ConvertFrom-ModelResponseContent -Response $responseText
            if ($content -and $content.Trim().Length -gt 0) {
                if ($candidateModel -ne $ModelName) {
                    Write-Output "[WARN] $ModelName returned empty output; generated report with $candidateModel."
                }
                return $content
            }
            $lastError = "$candidateModel returned empty model output."
        }
        catch {
            $lastError = ($_.Exception.Message -replace "Bearer\s+[A-Za-z0-9._-]+", "Bearer [REDACTED]")
        }
    }

    throw "Direct GPT report generation failed. $lastError"
}

function ConvertFrom-ModelResponseContent {
    param([Parameter(Mandatory = $true)]$Response)

    if ($Response -is [string]) {
        $text = [string]$Response
        $lines = $text -split "(`r`n|`n|`r)"
        $parts = New-Object System.Collections.Generic.List[string]
        foreach ($line in $lines) {
            if (-not $line.StartsWith("data:")) {
                continue
            }
            $data = $line.Substring(5).Trim()
            if (-not $data -or $data -eq "[DONE]") {
                continue
            }
            try {
                $chunk = $data | ConvertFrom-Json -Depth 50
            }
            catch {
                continue
            }
            $chunkText = ConvertFrom-ModelResponseContent -Response $chunk
            if ($chunkText -and $chunkText.Length -gt 0) {
                $parts.Add($chunkText) | Out-Null
            }
        }
        if ($parts.Count -gt 0) {
            return ($parts -join "")
        }
        return $text
    }

    if (($Response.PSObject.Properties.Name -contains "choices") -and $Response.choices -and $Response.choices.Count -gt 0) {
        $parts = New-Object System.Collections.Generic.List[string]
        foreach ($choice in @($Response.choices)) {
            if (($choice.PSObject.Properties.Name -contains "message") -and $choice.message) {
                $message = $choice.message
                if (($message.PSObject.Properties.Name -contains "content") -and $message.content) {
                    $parts.Add([string]$message.content) | Out-Null
                }
            }
            if (($choice.PSObject.Properties.Name -contains "delta") -and $choice.delta) {
                $delta = $choice.delta
                if (($delta.PSObject.Properties.Name -contains "content") -and $delta.content) {
                    $parts.Add([string]$delta.content) | Out-Null
                }
            }
            if (($choice.PSObject.Properties.Name -contains "text") -and $choice.text) {
                $parts.Add([string]$choice.text) | Out-Null
            }
        }
        return (($parts | Where-Object { $_ -and $_.Length -gt 0 }) -join "")
    }

    return ""
}

function Get-IsoWeekStamp {
    $now = Get-Date
    if ("System.Globalization.ISOWeek" -as [type]) {
        $isoYear = [System.Globalization.ISOWeek]::GetYear($now)
        $isoWeek = [System.Globalization.ISOWeek]::GetWeekOfYear($now)
        return ("{0}-W{1:D2}" -f $isoYear, $isoWeek)
    }

    $calendar = [System.Globalization.CultureInfo]::InvariantCulture.Calendar
    $day = $calendar.GetDayOfWeek($now)
    if (($day -ge [System.DayOfWeek]::Monday) -and ($day -le [System.DayOfWeek]::Wednesday)) {
        $now = $now.AddDays(3)
    }
    $isoYear = $now.Year
    $isoWeek = $calendar.GetWeekOfYear($now, [System.Globalization.CalendarWeekRule]::FirstFourDayWeek, [System.DayOfWeek]::Monday)
    return ("{0}-W{1:D2}" -f $isoYear, $isoWeek)
}

function Get-SafeLabel {
    param(
        [Parameter(Mandatory = $true)][string]$RootPath,
        [string]$ExplicitLabel = ""
    )

    if ($ExplicitLabel -and $ExplicitLabel.Trim().Length -gt 0) {
        $rawLabel = $ExplicitLabel.Trim()
    }
    else {
        $trimmed = $RootPath.TrimEnd("\", "/")
        $rawLabel = Split-Path -Leaf $trimmed
        if (-not $rawLabel -or $rawLabel.Trim().Length -eq 0) {
            $rawLabel = "project"
        }
    }
    return ($rawLabel -replace "[^A-Za-z0-9_-]", "-")
}

function Get-CombinedLabel {
    param(
        [Parameter(Mandatory = $true)][string[]]$RootPaths,
        [string]$ExplicitLabel = ""
    )

    if ($ExplicitLabel -and $ExplicitLabel.Trim().Length -gt 0) {
        return (Get-SafeLabel -RootPath $RootPaths[0] -ExplicitLabel $ExplicitLabel)
    }
    if ($RootPaths.Count -eq 1) {
        return (Get-SafeLabel -RootPath $RootPaths[0])
    }
    return "all-projects"
}

function Get-CombinedGlimpseJson {
    param(
        [Parameter(Mandatory = $true)][string]$GlimpseExe,
        [Parameter(Mandatory = $true)][string[]]$RootPaths,
        [Parameter(Mandatory = $true)][string]$ReportMode,
        [Parameter(Mandatory = $true)][string]$SinceValue,
        [string]$UntilValue = ""
    )

    if ($RootPaths.Count -eq 1) {
        Write-Host "[i] Running gitglimpse $ReportMode for $($RootPaths[0]) since '$SinceValue'"
        return (Invoke-Glimpse -GlimpseExe $GlimpseExe -WorkDir $RootPaths[0] -ReportMode $ReportMode -SinceValue $SinceValue -UntilValue $UntilValue)
    }

    $rootReports = @()
    foreach ($rootPath in $RootPaths) {
        Write-Host "[i] Running gitglimpse $ReportMode for $rootPath since '$SinceValue'"
        $rootRaw = Invoke-Glimpse -GlimpseExe $GlimpseExe -WorkDir $rootPath -ReportMode $ReportMode -SinceValue $SinceValue -UntilValue $UntilValue
        try {
            $parsed = $rootRaw | ConvertFrom-Json -Depth 100
        }
        catch {
            $parsed = $rootRaw
        }
        $rootReports += [pscustomobject]@{
            root = $rootPath
            label = (Get-SafeLabel -RootPath $rootPath)
            gitglimpse = $parsed
        }
    }

    $combined = [pscustomobject]@{
        mode = $ReportMode
        since = $SinceValue
        until = $UntilValue
        generated_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
        roots = $rootReports
    }
    return ($combined | ConvertTo-Json -Depth 100)
}

function Invoke-CodexReport {
    param(
        [Parameter(Mandatory = $true)][string]$Token,
        [Parameter(Mandatory = $true)][string]$ModelName,
        [Parameter(Mandatory = $true)][string]$ReportMode,
        [Parameter(Mandatory = $true)][string]$RawJson,
        [Parameter(Mandatory = $true)][string]$OutFile,
        [Parameter(Mandatory = $true)][string]$WorkDir
    )

    $codexHome = Join-Path $env:USERPROFILE ".codex-gpt55-token"
    $env:CODEX_HOME = $codexHome
    $env:OPENAI_API_KEY = $Token
    $env:GPT55_PRO_API_KEY = $Token

    if ($ReportMode -eq "weekly") {
        $instruction = @"
Generate a Chinese weekly engineering report from the engineering activity JSON below.

Required structure:
# Weekly Project Report
## One-line Summary
## Main Outcomes
## Important Technical Changes
## Product / User Impact
## Quality, Verification, and Deployment
## Risks / Blockers
## Next Week Focus
## Evidence

Rules:
- Use only the provided engineering activity JSON.
- Write for a manager, not for a compiler.
- Group by real work themes.
- Do not invent meetings, tests, releases, or blockers.
- Mention uncertainty if the git data is insufficient.
- Keep it compact but specific.
- Return only the Markdown report.

gitglimpse JSON:
$RawJson
"@
    }
    else {
        $instruction = @"
Generate a Chinese daily engineering report from the engineering activity JSON below.

Required structure:
# Daily Project Report
## One-line Summary
## Completed Today
## Key Changes
## Product / User Impact
## Quality, Verification, and Deployment
## Risks / Blockers
## Tomorrow Focus
## Evidence

Rules:
- Use only the provided engineering activity JSON.
- Write for a manager, not for a compiler.
- Group by real work themes.
- Do not invent meetings, tests, releases, or blockers.
- Mention uncertainty if the git data is insufficient.
- Keep it compact but specific.
- Return only the Markdown report.

gitglimpse JSON:
$RawJson
"@
    }

    if (Test-Path -LiteralPath $OutFile) {
        Remove-Item -LiteralPath $OutFile -Force
    }

    $promptFile = Join-Path ([System.IO.Path]::GetTempPath()) ("project-report-prompt-" + [guid]::NewGuid().ToString("N") + ".txt")
    Write-Utf8File -Path $promptFile -Content $instruction
    try {
        $prompt = Get-Content -LiteralPath $promptFile -Raw
        $codexArgs = @(
            "exec",
            "--ephemeral",
            "--cd",
            $WorkDir,
            "--model",
            $ModelName,
            "--output-last-message",
            $OutFile,
            $prompt
        )
        $codexExe = (Get-Command codex -ErrorAction Stop).Source
        & $codexExe @codexArgs *> $null
        $codexExitCode = $LASTEXITCODE
        if ($codexExitCode -ne 0) {
            throw "Codex report generation failed with exit code ${codexExitCode}."
        }
    }
    finally {
        if (Test-Path -LiteralPath $promptFile) {
            Remove-Item -LiteralPath $promptFile -Force
        }
    }

    if (-not (Test-Path -LiteralPath $OutFile)) {
        throw "Codex did not write report output: $OutFile"
    }
    return (Get-Content -LiteralPath $OutFile -Raw)
}

function New-FallbackManagerReport {
    param(
        [Parameter(Mandatory = $true)][string]$ReportMode,
        [Parameter(Mandatory = $true)][string]$RawJson,
        [Parameter(Mandatory = $true)][string]$ErrorSummary
    )

    try {
        $parsed = $RawJson | ConvertFrom-Json -Depth 100
    }
    catch {
        $parsed = $null
    }

    $lines = New-Object System.Collections.Generic.List[string]
    $activityJsonLabel = "activity JSON"
    if ($parsed -and ($parsed.PSObject.Properties.Name -contains "git_activity")) {
        $activityJsonLabel = "combined activity JSON"
    }

    if ($ReportMode -eq "weekly") {
        $lines.Add("# Weekly Project Report")
        $lines.Add("## One-line Summary")
        $lines.Add("本周报告已生成，但模型润色步骤失败；以下内容基于 $activityJsonLabel 自动整理。")
        $lines.Add("## Main Outcomes")
    }
    else {
        $lines.Add("# Daily Project Report")
        $lines.Add("## One-line Summary")
        $lines.Add("今日报告已生成，但模型润色步骤失败；以下内容基于 $activityJsonLabel 自动整理。")
        $lines.Add("## Completed Today")
    }

    $hasWork = $false
    $gitRoots = @()
    if ($parsed -and ($parsed.PSObject.Properties.Name -contains "git_activity") -and $parsed.git_activity) {
        if ($parsed.git_activity.PSObject.Properties.Name -contains "roots") {
            $gitRoots = @($parsed.git_activity.roots)
        }
        else {
            $gitRoots = @([pscustomobject]@{
                label = "git"
                gitglimpse = $parsed.git_activity
            })
        }
    }
    elseif ($parsed -and ($parsed.PSObject.Properties.Name -contains "roots")) {
        $gitRoots = @($parsed.roots)
    }

    if ($gitRoots.Count -gt 0) {
        foreach ($root in $gitRoots) {
            $label = [string]$root.label
            $glimpse = $root.gitglimpse
            if ($glimpse -is [string]) {
                $lines.Add("- ${label}: $glimpse")
                continue
            }
            $tasks = @()
            if ($glimpse -and ($glimpse.PSObject.Properties.Name -contains "days")) {
                foreach ($day in $glimpse.days) {
                    if ($day.PSObject.Properties.Name -contains "tasks") {
                        $tasks += @($day.tasks)
                    }
                }
            }
            if ($tasks.Count -eq 0) {
                $lines.Add("- ${label}: gitglimpse 未发现该时间窗口内的提交任务。")
                continue
            }
            $hasWork = $true
            foreach ($task in $tasks) {
                $title = "未命名任务"
                if ($task.PSObject.Properties.Name -contains "title") {
                    $title = [string]$task.title
                }
                elseif ($task.PSObject.Properties.Name -contains "summary") {
                    $title = [string]$task.summary
                }
                $lines.Add("- ${label}: $title")
            }
        }
    }

    if ($parsed -and ($parsed.PSObject.Properties.Name -contains "file_activity") -and $parsed.file_activity) {
        foreach ($root in @($parsed.file_activity.roots)) {
            $label = [string]$root.label
            $files = @($root.files)
            if ($files.Count -eq 0) {
                $lines.Add("- ${label}: 文件日期扫描未发现该时间窗口内的非生成文件改动。")
                continue
            }
            $hasWork = $true
            $lines.Add("- ${label}: 文件日期扫描发现 $($root.changed_file_count) 个代表性改动文件。")
            foreach ($file in ($files | Select-Object -First 12)) {
                $lines.Add("  - $($file.path)")
            }
        }
    }

    if ((-not $parsed) -or (($gitRoots.Count -eq 0) -and (-not ($parsed.PSObject.Properties.Name -contains "file_activity")))) {
        $lines.Add("- 未能解析活动 JSON；请查看同名 `.activity.json` 或 `.gitglimpse.json` 文件。")
    }
    if (-not $hasWork) {
        $lines.Add("- 当前时间窗口内没有可归纳的提交或文件日期工作。")
    }

    if ($ReportMode -eq "weekly") {
        $lines.Add("## Important Technical Changes")
    }
    else {
        $lines.Add("## Key Changes")
    }
    $lines.Add("- 原始工程活动已保存为同名活动 JSON，可用于后续复核。")
    $lines.Add("## Product / User Impact")
    $lines.Add("- 本次 fallback 报告只反映提交和文件日期证据，未额外推断产品影响。")
    $lines.Add("## Quality, Verification, and Deployment")
    $lines.Add("- 报告工具已完成原始活动数据生成；模型生成步骤失败后使用本地 fallback 生成 Markdown。")
    $lines.Add("## Risks / Blockers")
    $lines.Add("- 模型润色步骤失败：$ErrorSummary")
    if ($ReportMode -eq "weekly") {
        $lines.Add("## Next Week Focus")
    }
    else {
        $lines.Add("## Tomorrow Focus")
    }
    $lines.Add("- 恢复 Codex/模型调用环境后，重新运行报告生成以获得更完整的管理层摘要。")
    if ($parsed -and ($parsed.PSObject.Properties.Name -contains "personal_profile") -and $parsed.personal_profile -and $parsed.personal_profile.available) {
        $lines.Add("## Personal Growth Coach")
        $lines.Add("- 本次报告已加载个人能力评估 profile；模型恢复后应基于该 profile 输出短板提醒。")
        $lines.Add("- 固定提醒方向：业务影响、客户交付案例、合规安全、英文 demo、GitHub portfolio、RAG/Agent eval。")
    }
    $lines.Add("## Evidence")
    $lines.Add("- Source: activity JSON generated by `ops/run-project-report.ps1`.")

    return ($lines -join "`r`n")
}

$projectRoot = Get-ProjectRoot
if (-not $Root -or $Root.Count -eq 0) {
    $Root = @($projectRoot)
}
if (-not $OutputDir -or $OutputDir.Trim().Length -eq 0) {
    $OutputDir = Get-DefaultReportOutputDir
}

foreach ($rootPath in $Root) {
    if (-not (Test-Path -LiteralPath $rootPath)) {
        throw "Root not found: $rootPath"
    }
}

$venv = Join-Path $projectRoot ".files\report-venv"
$pythonExe = Join-Path $venv "Scripts\python.exe"
$glimpseExe = Join-Path $venv "Scripts\glimpse.exe"
$gitglimpseRoot = Join-Path $projectRoot "third_party\gitglimpse"

if ((-not $SkipGitActivity) -and (-not (Test-Path -LiteralPath $gitglimpseRoot))) {
    throw "gitglimpse is not cloned. Expected: $gitglimpseRoot"
}

if ((-not $SkipGitActivity) -and (-not (Test-Path -LiteralPath $pythonExe))) {
    python -m venv $venv
}

if ((-not $SkipGitActivity) -and (-not (Test-Path -LiteralPath $glimpseExe))) {
    & $pythonExe -m pip install -e "$gitglimpseRoot[llm]"
}

if (-not $Since -or $Since.Trim().Length -eq 0) {
    if ($Mode -eq "weekly") {
        $Since = "7 days ago"
    }
    else {
        $Since = "yesterday"
    }
}

$stamp = Get-Date -Format "yyyy-MM-dd"
$week = Get-IsoWeekStamp
$safeLabel = Get-CombinedLabel -RootPaths $Root -ExplicitLabel $Label
if ($Mode -eq "weekly") {
    $baseName = "$week-$safeLabel-weekly"
}
else {
    $baseName = "$stamp-$safeLabel-daily"
}

New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
$rawExtension = "gitglimpse.json"
if ($IncludeFileActivity -or $SkipGitActivity -or ($PersonalProfilePath -and (Test-Path -LiteralPath $PersonalProfilePath))) {
    $rawExtension = "activity.json"
}
$rawPath = Join-Path $OutputDir "$baseName.$rawExtension"
$reportPath = Join-Path $OutputDir "$baseName.md"

$gitActivity = $null
if (-not $SkipGitActivity) {
    $gitRaw = Get-CombinedGlimpseJson -GlimpseExe $glimpseExe -RootPaths $Root -ReportMode $Mode -SinceValue $Since -UntilValue $Until
    try {
        $gitActivity = $gitRaw | ConvertFrom-Json -Depth 100
    }
    catch {
        $gitActivity = $gitRaw
    }
}

$fileActivity = $null
if ($IncludeFileActivity) {
    $sinceDate = Resolve-SinceDate -ReportMode $Mode -SinceValue $Since
    $fileActivity = Get-FileActivity -RootPaths $Root -SinceDate $sinceDate -MaxFiles $MaxFilesPerRoot
}

$personalProfile = Get-PersonalProfile -Path $PersonalProfilePath
if ($IncludeFileActivity -or $SkipGitActivity -or $personalProfile.available) {
    $raw = New-ActivityJson -ReportMode $Mode -SinceValue $Since -UntilValue $Until -GitActivity $gitActivity -FileActivity $fileActivity -PersonalProfile $personalProfile
}
else {
    if ($gitActivity -is [string]) {
        $raw = $gitActivity
    }
    else {
        $raw = $gitActivity | ConvertTo-Json -Depth 100
    }
}
Write-Utf8File -Path $rawPath -Content $raw
Write-Output "[OK] Raw activity JSON: $rawPath"

if ($RawOnly) {
    Write-Output "[OK] Raw-only mode complete"
    exit 0
}

Write-Output "[i] Generating manager report with $Model"
if ($ForceFallback) {
    Write-Output "[i] ForceFallback enabled; writing deterministic fallback report."
    $fallbackReport = New-FallbackManagerReport -ReportMode $Mode -RawJson $raw -ErrorSummary "Model generation skipped by ForceFallback for scheduled reliability."
    Write-Utf8File -Path $reportPath -Content $fallbackReport
}
elseif ($DirectApi) {
    $token = Get-Token
    $endpoint = ($ApiBase.TrimEnd("/") + "/chat/completions")
    $report = Invoke-GptReport -Token $token -Endpoint $endpoint -ModelName $Model -ReportMode $Mode -RawJson $raw
    Write-Utf8File -Path $reportPath -Content $report
}
else {
    $token = Get-Token
    try {
        Invoke-CodexReport -Token $token -ModelName $Model -ReportMode $Mode -RawJson $raw -OutFile $reportPath -WorkDir $projectRoot | Out-Null
    }
    catch {
        $errorSummary = ($_.Exception.Message -replace "Bearer\s+[A-Za-z0-9._-]+", "Bearer [REDACTED]")
        Write-Output "[WARN] Model report generation failed; writing fallback report. $errorSummary"
        $fallbackReport = New-FallbackManagerReport -ReportMode $Mode -RawJson $raw -ErrorSummary $errorSummary
        Write-Utf8File -Path $reportPath -Content $fallbackReport
    }
}
Write-Output "[OK] Report: $reportPath"
