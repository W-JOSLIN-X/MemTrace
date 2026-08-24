[CmdletBinding()]
param(
    [string]$BaseUrl = 'http://127.0.0.1:8000',
    [string]$PythonExe = '',
    [ValidateRange(5, 300)]
    [int]$TimeoutSeconds = 60,
    [ValidateRange(1, 30)]
    [int]$ReconnectProbeSeconds = 8
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$script:ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$script:BaseUrl = $BaseUrl.TrimEnd('/')
$defaultPython = Join-Path $script:ProjectRoot 'apps\api\.venv\Scripts\python.exe'
$script:PythonExe = if (-not [string]::IsNullOrWhiteSpace($PythonExe)) {
    $PythonExe
}
elseif ([System.IO.File]::Exists($defaultPython)) {
    $defaultPython
}
else {
    'python'
}
$script:CookiePath = [System.IO.Path]::GetTempFileName()
$script:RunNonce = [Guid]::NewGuid().ToString('N')
$script:WriteSequence = 0

function Assert-Condition {
    param(
        [bool]$Condition,
        [string]$Message
    )

    if (-not $Condition) {
        throw "SMOKE ASSERTION FAILED: $Message"
    }
}

function Remove-TemporaryFile {
    param([AllowNull()][string]$Path)

    if ($Path -and [System.IO.File]::Exists($Path)) {
        [System.IO.File]::Delete($Path)
    }
}

function Read-SharedUtf8Text {
    param([string]$Path)

    $stream = [System.IO.FileStream]::new(
        $Path,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::ReadWrite -bor [System.IO.FileShare]::Delete
    )
    $reader = $null
    try {
        $reader = [System.IO.StreamReader]::new(
            $stream,
            [System.Text.Encoding]::UTF8,
            $true,
            4096,
            $true
        )
        return $reader.ReadToEnd()
    }
    finally {
        if ($null -ne $reader) {
            $reader.Dispose()
        }
        $stream.Dispose()
    }
}

function Invoke-CurlJson {
    param(
        [ValidateSet('GET', 'POST')]
        [string]$Method,
        [string]$Url,
        [AllowNull()][object]$Body = $null
    )

    $responsePath = [System.IO.Path]::GetTempFileName()
    $requestPath = $null
    try {
        $arguments = @(
            '--silent',
            '--show-error',
            '--request', $Method,
            '--max-time', [string]$TimeoutSeconds,
            '--output', $responsePath,
            '--write-out', '%{http_code}',
            '--cookie', $script:CookiePath,
            '--cookie-jar', $script:CookiePath
        )

        if ($Method -eq 'POST') {
            $script:WriteSequence++
            $requestPath = [System.IO.Path]::GetTempFileName()
            $json = $Body | ConvertTo-Json -Depth 30 -Compress
            [System.IO.File]::WriteAllText($requestPath, $json, [System.Text.UTF8Encoding]::new($false))
            $arguments += @(
                '--header', 'Content-Type: application/json',
                '--header', "Idempotency-Key: smoke-$($script:RunNonce)-$($script:WriteSequence.ToString('D4'))",
                '--data-binary', "@$requestPath"
            )
        }

        $arguments += $Url
        $statusOutput = & curl.exe @arguments
        $curlExitCode = $LASTEXITCODE
        Assert-Condition ($curlExitCode -eq 0) "curl failed for $Method $Url with exit code $curlExitCode"

        $statusText = ($statusOutput | Out-String).Trim()
        Assert-Condition ($statusText -match '^\d{3}$') "curl returned an invalid HTTP status: $statusText"
        $responseText = [System.IO.File]::ReadAllText($responsePath, [System.Text.Encoding]::UTF8)
        $parsedBody = $null
        if (-not [string]::IsNullOrWhiteSpace($responseText)) {
            $parsedBody = $responseText | ConvertFrom-Json
        }

        return [pscustomobject]@{
            StatusCode = [int]$statusText
            Body = $parsedBody
            RawBody = $responseText
        }
    }
    finally {
        Remove-TemporaryFile $responsePath
        Remove-TemporaryFile $requestPath
    }
}

function Invoke-SseCurl {
    param([string]$Url)

    $headerPath = [System.IO.Path]::GetTempFileName()
    $outputPath = [System.IO.Path]::GetTempFileName()
    $errorPath = [System.IO.Path]::GetTempFileName()
    try {
        $arguments = @(
            '--silent',
            '--show-error',
            '--no-buffer',
            '--max-time', [string]$TimeoutSeconds,
            '--dump-header', $headerPath,
            '--output', $outputPath,
            '--stderr', $errorPath,
            '--cookie', $script:CookiePath,
            $Url
        )
        & curl.exe @arguments
        $curlExitCode = $LASTEXITCODE
        $errorText = [System.IO.File]::ReadAllText($errorPath, [System.Text.Encoding]::UTF8).Trim()
        Assert-Condition ($curlExitCode -eq 0) "SSE curl failed for $Url with exit code $curlExitCode. $errorText"
        return [pscustomobject]@{
            Text = [System.IO.File]::ReadAllText($outputPath, [System.Text.Encoding]::UTF8)
            Headers = [System.IO.File]::ReadAllText($headerPath, [System.Text.Encoding]::ASCII)
        }
    }
    finally {
        Remove-TemporaryFile $headerPath
        Remove-TemporaryFile $outputPath
        Remove-TemporaryFile $errorPath
    }
}

function ConvertFrom-SseText {
    param([string]$Text)

    $events = [System.Collections.Generic.List[object]]::new()
    $wireEvent = $null
    $wireId = $null
    $dataLines = [System.Collections.Generic.List[string]]::new()
    $lines = @($Text -split "`r?`n") + @('')

    foreach ($line in $lines) {
        if ($line -eq '') {
            if ($null -ne $wireEvent -or $dataLines.Count -gt 0) {
                Assert-Condition ($null -ne $wireEvent) 'SSE frame has data but no event field'
                Assert-Condition ($dataLines.Count -gt 0) "SSE event $wireEvent has no data field"
                $payload = ($dataLines -join "`n") | ConvertFrom-Json
                Assert-Condition ($payload.event_type -eq $wireEvent) "wire event $wireEvent differs from data.event_type $($payload.event_type)"

                if ($null -eq $wireId) {
                    Assert-Condition ($null -eq $payload.event_seq) "transient event $wireEvent unexpectedly has event_seq"
                }
                else {
                    $parsedId = 0
                    Assert-Condition ([int]::TryParse($wireId, [ref]$parsedId)) "SSE id is not an integer: $wireId"
                    Assert-Condition ($payload.event_seq -eq $parsedId) "wire id $parsedId differs from data.event_seq $($payload.event_seq)"
                }

                $events.Add([pscustomobject]@{
                    Event = $wireEvent
                    Id = if ($null -eq $wireId) { $null } else { [int]$wireId }
                    Payload = $payload
                })
            }
            $wireEvent = $null
            $wireId = $null
            $dataLines = [System.Collections.Generic.List[string]]::new()
            continue
        }

        if ($line.StartsWith(':')) {
            continue
        }
        if ($line.StartsWith('event:')) {
            $wireEvent = $line.Substring(6).TrimStart()
            continue
        }
        if ($line.StartsWith('id:')) {
            $wireId = $line.Substring(3).TrimStart()
            continue
        }
        if ($line.StartsWith('data:')) {
            $dataLines.Add($line.Substring(5).TrimStart())
        }
    }

    return $events.ToArray()
}

function Get-TraceSignature {
    param([object[]]$Events)

    $signature = [System.Collections.Generic.List[string]]::new()
    $chunkSeen = $false
    foreach ($item in $Events) {
        if ($item.Event -eq 'agent.chunk') {
            if (-not $chunkSeen) {
                $signature.Add('agent.chunk+')
                $chunkSeen = $true
            }
            continue
        }
        if ($item.Event -eq 'task.stage') {
            $signature.Add("task.stage:$($item.Payload.data.stage)")
        }
        else {
            $signature.Add([string]$item.Event)
        }
    }
    return $signature.ToArray()
}

function Assert-Sequence {
    param(
        [string[]]$Actual,
        [string[]]$Expected,
        [string]$Label
    )

    Assert-Condition ($Actual.Count -eq $Expected.Count) "$Label count differs. Actual: $($Actual -join ', ')"
    for ($index = 0; $index -lt $Expected.Count; $index++) {
        Assert-Condition ($Actual[$index] -eq $Expected[$index]) "$Label differs at $index. Expected $($Expected[$index]), got $($Actual[$index])"
    }
}

function Get-ChunkState {
    param(
        [object[]]$Events,
        [int]$InitialOffset = 0
    )

    $offset = $InitialOffset
    $text = [System.Text.StringBuilder]::new()
    $chunks = @($Events | Where-Object { $_.Event -eq 'agent.chunk' })
    $expectedChunkSequence = 1
    $previousChunkSequence = $null
    foreach ($item in $chunks) {
        $data = $item.Payload.data
        if ($InitialOffset -eq 0) {
            Assert-Condition ($data.chunk_seq -eq $expectedChunkSequence) "chunk_seq is not contiguous from 1"
            $expectedChunkSequence++
        }
        elseif ($null -ne $previousChunkSequence) {
            Assert-Condition ($data.chunk_seq -gt $previousChunkSequence) "reconnected chunk_seq is not strictly increasing"
        }
        $previousChunkSequence = [int]$data.chunk_seq
        Assert-Condition ($data.start_offset -eq $offset) "chunk starts at $($data.start_offset), expected $offset"
        $offset += [System.Text.Encoding]::UTF8.GetByteCount([string]$data.delta)
        Assert-Condition ($data.end_offset -eq $offset) "chunk end_offset $($data.end_offset) does not match UTF-8 byte offset $offset"
        [void]$text.Append([string]$data.delta)
    }

    return [pscustomobject]@{
        Text = $text.ToString()
        EndOffset = $offset
        Count = $chunks.Count
    }
}

function Assert-SseHeaders {
    param([string]$Headers)

    Assert-Condition ($Headers -match '(?im)^content-type:\s*text/event-stream(?:;\s*charset=utf-8)?\s*$') 'SSE Content-Type is missing or incorrect'
    Assert-Condition ($Headers -match '(?im)^cache-control:\s*no-cache,\s*no-transform\s*$') 'SSE Cache-Control is missing or incorrect'
    Assert-Condition ($Headers -match '(?im)^x-accel-buffering:\s*no\s*$') 'SSE proxy buffering is not disabled'
}

function Assert-TerminalSnapshot {
    param(
        [object]$Snapshot,
        [ValidateSet('succeeded', 'failed')]
        [string]$ExpectedStatus
    )

    Assert-Condition ($Snapshot.run_status -eq $ExpectedStatus) "snapshot run_status is $($Snapshot.run_status), expected $ExpectedStatus"
    Assert-Condition ($Snapshot.terminal -eq $true) 'terminal snapshot has terminal=false'
    $actualBytes = [System.Text.Encoding]::UTF8.GetByteCount([string]$Snapshot.partial_output)
    Assert-Condition ($Snapshot.end_offset -eq $actualBytes) "snapshot end_offset does not equal UTF-8 byte length"
    Assert-Condition ($Snapshot.offset_unit -eq 'utf8_bytes') 'snapshot offset_unit is not utf8_bytes'
    if ($ExpectedStatus -eq 'succeeded') {
        Assert-Condition ($null -ne $Snapshot.final_message) 'successful snapshot has no final_message'
        Assert-Condition ($Snapshot.final_message.content -eq $Snapshot.partial_output) 'final_message differs from partial_output'
        Assert-Condition ($null -eq $Snapshot.error) 'successful snapshot unexpectedly has an error'
    }
    else {
        Assert-Condition ($null -eq $Snapshot.final_message) 'failed snapshot unexpectedly has final_message'
        Assert-Condition ($null -ne $Snapshot.error) 'failed snapshot has no error'
    }
}

$pythonTrace = @(
    'task.created', 'task.stage:fingerprinting', 'task.fingerprinted',
    'task.stage:retrieving', 'memory.retrieval.started', 'task.stage:planning',
    'agent.plan.published', 'task.stage:tool_running', 'tool.called', 'tool.result',
    'task.stage:generating', 'agent.chunk+', 'run.metrics', 'run.completed', 'stream.done'
)
$failureTrace = @(
    'task.created', 'task.stage:fingerprinting', 'task.fingerprinted',
    'task.stage:retrieving', 'memory.retrieval.started', 'task.stage:planning',
    'agent.plan.published', 'task.stage:generating', 'agent.chunk+', 'run.metrics',
    'task.stage:failed', 'run.failed', 'error', 'stream.done'
)

try {
    Write-Host '[1/9] Validate schemas and fixtures'
    & $script:PythonExe (Join-Path $script:ProjectRoot 'scripts\day1\validate_fixtures.py')
    Assert-Condition ($LASTEXITCODE -eq 0) 'fixture validator failed'

    $fixtureRoot = Join-Path $script:ProjectRoot 'fixtures\day1'
    $demo = Get-Content -LiteralPath (Join-Path $fixtureRoot 'demo_core.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $pythonFixture = Get-Content -LiteralPath (Join-Path $fixtureRoot 'mock_sse_python_success.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $noToolFixture = Get-Content -LiteralPath (Join-Path $fixtureRoot 'mock_sse_no_tool_success.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $failureFixture = Get-Content -LiteralPath (Join-Path $fixtureRoot 'mock_sse_failure.json') -Raw -Encoding UTF8 | ConvertFrom-Json

    Write-Host '[2/9] Health and readiness'
    $health = Invoke-CurlJson -Method GET -Url "$script:BaseUrl/api/v1/health"
    Assert-Condition ($health.StatusCode -eq 200) "health returned $($health.StatusCode)"
    Assert-Condition ($health.Body.status -eq 'ok') 'health body is not ok'
    $ready = Invoke-CurlJson -Method GET -Url "$script:BaseUrl/api/v1/ready"
    Assert-Condition ($ready.StatusCode -eq 200) "ready returned $($ready.StatusCode)"
    Assert-Condition ($ready.Body.status -eq 'ready') 'ready body is not ready'
    Assert-Condition ($ready.Body.provider_mode -eq 'mock') 'Day 2 smoke must run against visibly labelled Mock mode'

    Write-Host '[3/9] Establish blank_demo session'
    $demoSession = Invoke-CurlJson -Method POST -Url "$script:BaseUrl/api/v1/session/demo" -Body ([ordered]@{ demo_alias = 'blank_demo' })
    Assert-Condition ($demoSession.StatusCode -eq 200) "session bootstrap returned $($demoSession.StatusCode)"
    Assert-Condition ($demoSession.Body.demo_alias -eq 'blank_demo') 'session bootstrap returned the wrong alias'

    Write-Host '[4/9] Rejection paths, manual scenario rejection, and unified error envelope'
    foreach ($caseId in @('empty_rejected', 'whitespace_rejected', 'overlong_rejected')) {
        $case = $demo.cases | Where-Object { $_.id -eq $caseId }
        if ($caseId -eq 'overlong_rejected') {
            $request = [ordered]@{
                task_text = ([string]$case.input_builder.repeat * [int]$case.input_builder.count)
                memory_mode = $case.request_template.memory_mode
                current_constraints = $case.request_template.current_constraints
            }
        }
        else {
            $request = $case.request
        }
        $response = Invoke-CurlJson -Method POST -Url "$script:BaseUrl/api/v1/tasks" -Body $request
        Assert-Condition ($response.StatusCode -eq 422) "$caseId returned $($response.StatusCode), expected 422"
        Assert-Condition ($response.Body.error.code -eq 'VALIDATION_ERROR') "$caseId did not use VALIDATION_ERROR"
        Assert-Condition ($response.Body.error.request_id -match '^req_[0-9A-HJKMNP-TV-Z]{26}$') "$caseId has an invalid request_id"
    }
    $manualScenarioRequest = [ordered]@{
        task_text = '解释 Python 列表越界'
        scenario = 'programming_learning'
        memory_mode = 'on'
        current_constraints = [ordered]@{
            response_policy = 'default'
            urgency = 'normal'
            memory_disabled = $false
            source = 'ui'
        }
    }
    $manualScenario = Invoke-CurlJson -Method POST -Url "$script:BaseUrl/api/v1/tasks" -Body $manualScenarioRequest
    Assert-Condition ($manualScenario.StatusCode -eq 422) 'manual scenario was not rejected with 422'

    Write-Host '[5/9] Python success: create, automatic classification, SSE, and snapshot'
    $created = Invoke-CurlJson -Method POST -Url "$script:BaseUrl/api/v1/tasks" -Body $pythonFixture.request
    Assert-Condition ($created.StatusCode -eq 202) "Python create returned $($created.StatusCode)"
    Assert-Condition ($created.Body.provider_mode -eq 'mock') 'created task is not labelled Mock'
    $pythonEventsUrl = "$script:BaseUrl$($created.Body.events_url)"
    $pythonStream = Invoke-SseCurl -Url $pythonEventsUrl
    Assert-SseHeaders $pythonStream.Headers
    $pythonEvents = @(ConvertFrom-SseText $pythonStream.Text)
    Assert-Sequence -Actual @(Get-TraceSignature $pythonEvents) -Expected $pythonTrace -Label 'Python success trace'
    $pythonChunks = Get-ChunkState $pythonEvents
    Assert-Condition ($pythonChunks.Text -eq $pythonFixture.expectations.chunk_text) 'Python SSE body differs from fixture'
    $pythonSnapshotResponse = Invoke-CurlJson -Method GET -Url "$script:BaseUrl/api/v1/tasks/$($created.Body.task_id)"
    Assert-Condition ($pythonSnapshotResponse.StatusCode -eq 200) 'Python snapshot did not return 200'
    Assert-TerminalSnapshot -Snapshot $pythonSnapshotResponse.Body -ExpectedStatus succeeded
    Assert-Condition ($pythonSnapshotResponse.Body.partial_output -eq $pythonChunks.Text) 'Python snapshot body differs from SSE body'
    Assert-Condition ($pythonSnapshotResponse.Body.scenario -eq $pythonSnapshotResponse.Body.fingerprint.domain) 'snapshot scenario differs from server fingerprint domain'
    Assert-Condition ($pythonSnapshotResponse.Body.fingerprint.classification_source -eq 'auto_rule_v1') 'classification source is not auto_rule_v1'

    Write-Host '[6/9] Forced provider failure: partial output and terminal error'
    $failedCreate = Invoke-CurlJson -Method POST -Url "$script:BaseUrl/api/v1/tasks" -Body $failureFixture.request
    Assert-Condition ($failedCreate.StatusCode -eq 202) "failure fixture create returned $($failedCreate.StatusCode)"
    $failureStream = Invoke-SseCurl -Url "$script:BaseUrl$($failedCreate.Body.events_url)"
    $failureEvents = @(ConvertFrom-SseText $failureStream.Text)
    Assert-Sequence -Actual @(Get-TraceSignature $failureEvents) -Expected $failureTrace -Label 'Failure trace'
    $failureChunks = Get-ChunkState $failureEvents
    $failedSnapshotResponse = Invoke-CurlJson -Method GET -Url "$script:BaseUrl/api/v1/tasks/$($failedCreate.Body.task_id)"
    Assert-TerminalSnapshot -Snapshot $failedSnapshotResponse.Body -ExpectedStatus failed
    Assert-Condition ($failedSnapshotResponse.Body.partial_output -eq $failureChunks.Text) 'failed snapshot did not retain partial SSE output'
    Assert-Condition ($failedSnapshotResponse.Body.error.code -eq 'PROVIDER_ERROR') 'forced failure did not expose PROVIDER_ERROR'

    Write-Host '[7/9] Unknown task returns unified 404'
    $missing = Invoke-CurlJson -Method GET -Url "$script:BaseUrl/api/v1/tasks/task_01J00000000000000000000999"
    Assert-Condition ($missing.StatusCode -eq 404) "unknown task returned $($missing.StatusCode)"
    Assert-Condition ($missing.Body.error.code -eq 'TASK_NOT_FOUND') 'unknown task did not use TASK_NOT_FOUND'

    Write-Host '[8/9] Forced disconnect and dual-cursor reconnect'
    $reconnectCreate = Invoke-CurlJson -Method POST -Url "$script:BaseUrl/api/v1/tasks" -Body $noToolFixture.request
    Assert-Condition ($reconnectCreate.StatusCode -eq 202) 'reconnect task creation failed'
    $reconnectUrl = "$script:BaseUrl$($reconnectCreate.Body.events_url)"
    $partialOut = [System.IO.Path]::GetTempFileName()
    $partialErr = [System.IO.Path]::GetTempFileName()
    $partialHeaders = [System.IO.Path]::GetTempFileName()
    $process = $null
    try {
        $arguments = @(
            '--silent', '--show-error', '--no-buffer',
            '--max-time', [string]$TimeoutSeconds,
            '--dump-header', $partialHeaders,
            '--cookie', $script:CookiePath,
            $reconnectUrl
        )
        $process = Start-Process -FilePath 'curl.exe' -ArgumentList $arguments -RedirectStandardOutput $partialOut -RedirectStandardError $partialErr -WindowStyle Hidden -PassThru
        $deadline = [DateTime]::UtcNow.AddSeconds($ReconnectProbeSeconds)
        $sawChunk = $false
        while ([DateTime]::UtcNow -lt $deadline -and -not $process.HasExited) {
            Start-Sleep -Milliseconds 50
            $partialText = Read-SharedUtf8Text $partialOut
            # Wait for a complete chunk frame. Seeing only the event line can
            # leave a truncated JSON payload and turn this recovery test into
            # a parser race rather than an SSE cursor test.
            if ($partialText -match '(?ms)^event:\s*agent\.chunk\s*\r?\ndata:\s*.+?\r?\n\r?\n') {
                $sawChunk = $true
                break
            }
        }
        Assert-Condition $sawChunk 'reconnect probe saw no chunk; run API with Mock chunk delay so disconnect can be exercised'
        if (-not $process.HasExited) {
            Stop-Process -Id $process.Id -Force
            $process.WaitForExit()
        }

        $partialText = Read-SharedUtf8Text $partialOut
        $partialEvents = @(ConvertFrom-SseText $partialText)
        Assert-Condition ($partialEvents.Count -gt 0) 'disconnect stream produced no complete SSE frame'
    }
    finally {
        if ($null -ne $process -and -not $process.HasExited) {
            Stop-Process -Id $process.Id -Force
            $process.WaitForExit()
        }
        Remove-TemporaryFile $partialOut
        Remove-TemporaryFile $partialErr
        Remove-TemporaryFile $partialHeaders
    }

    $preReconnectSnapshotResponse = Invoke-CurlJson -Method GET -Url "$script:BaseUrl/api/v1/tasks/$($reconnectCreate.Body.task_id)"
    Assert-Condition ($preReconnectSnapshotResponse.StatusCode -eq 200) 'pre-reconnect snapshot failed'
    $preReconnectSnapshot = $preReconnectSnapshotResponse.Body
    Assert-Condition ($preReconnectSnapshot.terminal -eq $false) 'task completed before reconnect; increase Mock chunk delay and rerun to prove cursor recovery'
    $cursorEvent = [int]$preReconnectSnapshot.last_persistent_event_seq
    $cursorOffset = [int]$preReconnectSnapshot.end_offset
    $cursorUrl = "$reconnectUrl`?after_event_seq=$cursorEvent&after_offset=$cursorOffset"
    $continuedStream = Invoke-SseCurl -Url $cursorUrl
    $continuedEvents = @(ConvertFrom-SseText $continuedStream.Text)
    foreach ($item in $continuedEvents) {
        if ($null -ne $item.Id) {
            Assert-Condition ($item.Id -gt $cursorEvent) "reconnect replayed persistent id $($item.Id) at or below cursor $cursorEvent"
        }
        if ($item.Event -eq 'agent.chunk') {
            Assert-Condition ($item.Payload.data.start_offset -ge $cursorOffset) "reconnect replayed chunk below offset cursor"
        }
    }
    $continuedChunks = Get-ChunkState -Events $continuedEvents -InitialOffset $cursorOffset
    Assert-Condition ($continuedChunks.Count -gt 0) 'dual-cursor reconnect delivered no continuation chunk'
    Assert-Condition (@($continuedEvents | Where-Object { $_.Event -eq 'stream.done' }).Count -eq 1) 'reconnected stream has no terminal stream.done'

    $finalReconnectSnapshotResponse = Invoke-CurlJson -Method GET -Url "$script:BaseUrl/api/v1/tasks/$($reconnectCreate.Body.task_id)"
    Assert-TerminalSnapshot -Snapshot $finalReconnectSnapshotResponse.Body -ExpectedStatus succeeded
    $reconstructed = [string]$preReconnectSnapshot.partial_output + [string]$continuedChunks.Text
    Assert-Condition ($reconstructed -eq $finalReconnectSnapshotResponse.Body.partial_output) 'dual-cursor reconstruction differs from final snapshot'
    Assert-Condition ($finalReconnectSnapshotResponse.Body.partial_output -eq $noToolFixture.expectations.chunk_text) 'reconnect final output differs from no-tool fixture'

    Write-Host '[9/9] Final result'
    Write-Host 'PASS: Day 2 Mock session/auto-classification/rejections/Python/failure/snapshot/SSE/dual-cursor smoke'
    Write-Host "MOCK_PYTHON_TASK_ID=$($created.Body.task_id)"
    Write-Host "MOCK_FAILURE_TASK_ID=$($failedCreate.Body.task_id)"
    Write-Host "MOCK_RECONNECT_TASK_ID=$($reconnectCreate.Body.task_id)"
    exit 0
}
catch {
    Write-Error $_
    exit 1
}
finally {
    Remove-TemporaryFile $script:CookiePath
}
