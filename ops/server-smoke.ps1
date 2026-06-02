param(
  [string]$BaseUrl = "http://127.0.0.1:3101",
  [string]$SshTarget = "",
  [int]$TimeoutSec = 360,
  [switch]$SkipVisualPost,
  [switch]$SkipSsh
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Write-Step($Name, $Status, $Detail = "") {
  $suffix = if ($Detail) { " - $Detail" } else { "" }
  Write-Host "[$Status] $Name$suffix"
}

function Fail($Message) {
  Write-Step "server-smoke" "FAIL" $Message
  exit 1
}

function Invoke-CheckedRequest {
  param(
    [string]$Name,
    [string]$Method,
    [string]$Url,
    [object]$Body = $null,
    [int]$RequestTimeoutSec = $TimeoutSec
  )

  $headers = @{ "Content-Type" = "application/json" }
  $jsonBody = if ($null -ne $Body) { $Body | ConvertTo-Json -Depth 20 -Compress } else { $null }
  $watch = [Diagnostics.Stopwatch]::StartNew()
  try {
    $response = if ($null -ne $Body) {
      Invoke-WebRequest -Uri $Url -Method $Method -Headers $headers -Body $jsonBody -TimeoutSec $RequestTimeoutSec -UseBasicParsing
    } else {
      Invoke-WebRequest -Uri $Url -Method $Method -TimeoutSec $RequestTimeoutSec -UseBasicParsing
    }
    $watch.Stop()
    Write-Step $Name "OK" "HTTP $($response.StatusCode), $($watch.ElapsedMilliseconds)ms, $($response.RawContentLength) bytes"
    $contentType = [string]$response.Headers["Content-Type"]
    $parsedJson = $null
    if ($response.Content -and $contentType -match "application/json") {
      $parsedJson = $response.Content | ConvertFrom-Json
    }
    return @{
      Response = $response
      Json = $parsedJson
      ElapsedMs = $watch.ElapsedMilliseconds
    }
  } catch {
    $watch.Stop()
    Fail "$Name failed after $($watch.ElapsedMilliseconds)ms: $($_.Exception.Message)"
  }
}

function Assert-True {
  param([bool]$Condition, [string]$Message)
  if (-not $Condition) {
    Fail $Message
  }
}

Write-Step "base url" "INFO" $BaseUrl

if (-not $SkipSsh -and $SshTarget) {
  $sshCommand = @'
set -e
echo "== pm2 =="
pm2 list --no-color | grep -E "photo-agent-(backend|web).*online"
echo "== resources =="
free -h
df -h /
echo "== nginx =="
nginx -t
echo "== docker =="
docker ps --format '{{.Names}} {{.Status}}' | grep -E 'photo-agent-(litellm|redis|langfuse-web|langfuse-worker|langfuse-clickhouse|langfuse-postgres|langfuse-redis|langfuse-minio)'
'@
  Write-Step "ssh runtime check" "RUN" $SshTarget
  ssh -o BatchMode=yes -o ConnectTimeout=8 $SshTarget $sshCommand
  if ($LASTEXITCODE -ne 0) {
    Fail "SSH runtime check failed for $SshTarget"
  }
  Write-Step "ssh runtime check" "OK"
}

$null = Invoke-CheckedRequest -Name "web home" -Method GET -Url "$BaseUrl/"
$null = Invoke-CheckedRequest -Name "visual page" -Method GET -Url "$BaseUrl/visual"
$health = Invoke-CheckedRequest -Name "backend health" -Method GET -Url "$BaseUrl/api-backend/health"
Assert-True ($health.Json.status -eq "ok") "Backend health did not return status=ok."

$visualGet = Invoke-CheckedRequest -Name "visual discover contract" -Method GET -Url "$BaseUrl/api-backend/v1/visual/discover"
Assert-True ($visualGet.Json.status -eq "ready") "Visual discover GET did not return ready status."

$answerOnlyBody = @{
  messages = @(@{ role = "user"; content = "河豚是什么，为什么危险？" })
  context = @{}
}
$answerOnly = Invoke-CheckedRequest -Name "travel answer-only chat" -Method POST -Url "$BaseUrl/api/travel/chat" -Body $answerOnlyBody
$answerParts = @($answerOnly.Json.message.parts)
$answerText = ($answerParts | Where-Object { $_.type -eq "text" } | Select-Object -First 1).text
$answerCards = ($answerParts | Where-Object { $_.type -eq "trip-cards" } | Select-Object -First 1).cards
Assert-True ($answerText -match "河豚|毒素|危险") "Answer-only chat did not explain the requested knowledge topic."
Assert-True (($answerCards | Measure-Object).Count -eq 0) "Answer-only chat unexpectedly returned place cards."

$placeBody = @{
  messages = @(@{ role = "user"; content = "福冈有什么好玩的？" })
  context = @{}
}
$place = Invoke-CheckedRequest -Name "travel place-card chat" -Method POST -Url "$BaseUrl/api/travel/chat" -Body $placeBody
$placeParts = @($place.Json.message.parts)
$cards = @((($placeParts | Where-Object { $_.type -eq "trip-cards" } | Select-Object -First 1).cards))
$map = ($placeParts | Where-Object { $_.type -eq "trip-map" } | Select-Object -First 1).map
Assert-True ($cards.Count -gt 0) "Place-card chat returned no recommendation cards."
Assert-True (@($map.pins).Count -gt 0) "Place-card chat returned no map pins."
Assert-True ($map.status -eq "ready") "Place-card map status was not ready."

if (-not $SkipVisualPost) {
  # A tiny valid PNG is enough to verify the live visual contract and model plumbing.
  $tinyPngBase64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
  $visualBody = @{
    images_base64 = @($tinyPngBase64)
    user_context_text = "server reliability smoke"
    exploration_focus = "auto"
    interest_tags = @("architecture")
  }
  $visualPost = Invoke-CheckedRequest -Name "visual discover POST" -Method POST -Url "$BaseUrl/api-backend/v1/visual/discover" -Body $visualBody
  Assert-True ([string]::IsNullOrWhiteSpace($visualPost.Json.one_line_answer) -eq $false) "Visual POST did not return one_line_answer."
  Assert-True (@($visualPost.Json.deep_cards).Count -eq 3) "Visual POST did not return exactly 3 deep cards."
}

Write-Step "server-smoke" "PASS" "all checks completed"
