param(
    [string]$SshHost = "drobotic",
    [string]$RemoteRepo = "/LargeModelDev/users/chendong.song/kinex",
    [int]$IntervalSeconds = 30,
    [switch]$Once,
    [string]$Model = ""
)

$ErrorActionPreference = "Stop"
$Queue = "experiment/tool-formulator/scripts/queue.py"
$Schema = "experiment/tool-formulator/schemas/result.schema.json"
$Worker = "$env:COMPUTERNAME-$PID"

function Invoke-Remote([string]$Command) {
    $output = & ssh $SshHost $Command
    if ($LASTEXITCODE -ne 0) { throw "remote command failed: $Command" }
    return $output
}

function Invoke-Formulation([string]$RequestId, [string]$RequestPath) {
    if ($RequestId -notmatch '^[a-z0-9][a-z0-9_.-]{2,127}$') { throw "invalid request id: $RequestId" }
    if ($RequestPath -notmatch '^experiment/tool-formulator/requests/[a-z0-9_.-]+$') { throw "invalid request path: $RequestPath" }

    Invoke-Remote "cd '$RemoteRepo' && python3 '$Queue' claim '$RequestId' --worker '$Worker'" | Out-Host
    $claimed = $true
    $temp = Join-Path ([IO.Path]::GetTempPath()) "kinex-formulator-$RequestId"
    New-Item -ItemType Directory -Path $temp -Force | Out-Null
    $localSchema = Join-Path $temp "result.schema.json"
    $localResult = Join-Path $temp "result.json"
    try {
        & scp "${SshHost}:${RemoteRepo}/${Schema}" $localSchema
        if ($LASTEXITCODE -ne 0) { throw "failed to download result schema" }

        $prompt = @"
You are the Kinex Tool Formulator. Work only in the remote repository available through SSH alias '$SshHost' at '$RemoteRepo'. Do not modify this local directory.

First, use SSH to read these remote files completely:
- $RemoteRepo/AGENTS.md
- $RemoteRepo/toolbox/AGENTS.md
- $RemoteRepo/.cursor/skills/kinex-tool-formulator/SKILL.md
- $RemoteRepo/$RequestPath/request.json
- $RemoteRepo/$RequestPath/prompt.md

Then perform the formulation workflow in that skill. Preserve unrelated remote changes. Do not deploy tools, start RoboTwin, or move any robot. Use the trace only as evidence. It is valid to conclude that no tool is needed. Run the required remote toolbox validation and tests before finishing.

Your final response must be only the JSON object required by the supplied output schema.
"@
        $arguments = @("exec", "--skip-git-repo-check", "-C", $PSScriptRoot, "-s", "danger-full-access", "--output-schema", $localSchema, "-o", $localResult, "-")
        if ($Model) { $arguments = @("exec", "--skip-git-repo-check", "-C", $PSScriptRoot, "-s", "danger-full-access", "-m", $Model, "--output-schema", $localSchema, "-o", $localResult, "-") }
        $prompt | & codex @arguments
        if ($LASTEXITCODE -ne 0) { throw "codex exec failed for $RequestId" }
        if (-not (Test-Path $localResult)) { throw "codex did not produce a result file" }

        $remoteCandidate = "$RemoteRepo/$RequestPath/result.candidate.json"
        & scp $localResult "${SshHost}:$remoteCandidate"
        if ($LASTEXITCODE -ne 0) { throw "failed to upload formulation result" }
        $claimed = $false
        Invoke-Remote "cd '$RemoteRepo' && python3 '$Queue' complete '$RequestId' --result '$RequestPath/result.candidate.json'" | Out-Host
    }
    catch {
        if ($claimed) {
            Invoke-Remote "cd '$RemoteRepo' && python3 '$Queue' release '$RequestId' --worker '$Worker' --reason 'workstation invocation failed'" | Out-Host
        }
        throw
    }
    finally {
        Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
    }
}

do {
    $raw = Invoke-Remote "cd '$RemoteRepo' && python3 '$Queue' pending --json"
    $requests = @($raw | ConvertFrom-Json)
    foreach ($request in $requests) {
        Invoke-Formulation ([string]$request.request_id) ([string]$request.path)
    }
    if ($Once) { break }
    Start-Sleep -Seconds $IntervalSeconds
} while ($true)

