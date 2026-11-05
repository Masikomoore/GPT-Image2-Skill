param(
    [switch]$AgentMode,
    [string]$Clients = "auto",
    [string]$BaseUrl = "",
    [string]$ApiKey = "",
    [string]$EnvPath = ""
)

$ErrorActionPreference = "Stop"
$RepoUrl = if ($env:GPT_IMAGE_SKILL_REPO) { $env:GPT_IMAGE_SKILL_REPO } else { "https://github.com/Masikomoore/GPT-Image2-Skill.git" }
$Branch = if ($env:GPT_IMAGE_SKILL_BRANCH) { $env:GPT_IMAGE_SKILL_BRANCH } else { "main" }

$ScriptDir = $PSScriptRoot
$TempDir = $null

try {
    if (-not $ScriptDir -or -not (Test-Path (Join-Path $ScriptDir "scripts\setup_skill.py"))) {
        $TempDir = Join-Path ([System.IO.Path]::GetTempPath()) ("gpt-image-skill-" + [System.Guid]::NewGuid().ToString("N"))
        New-Item -ItemType Directory -Path $TempDir | Out-Null
        Write-Host "Downloading GPT-Image2-Skill from $RepoUrl ($Branch)..."
        git clone --depth 1 --branch $Branch $RepoUrl $TempDir | Out-Null
        $ScriptDir = $TempDir
    }

    $PyArgs = @((Join-Path $ScriptDir "scripts\setup_skill.py"), "--repo-root", $ScriptDir, "--clients", $Clients)
    if ($AgentMode) { $PyArgs += "--agent-mode" }
    if ($BaseUrl) { $PyArgs += @("--base-url", $BaseUrl) }
    if ($ApiKey) { $PyArgs += @("--api-key", $ApiKey) }
    if ($EnvPath) { $PyArgs += @("--env-path", $EnvPath) }

    & python @PyArgs
} finally {
    if ($TempDir -and (Test-Path $TempDir)) {
        Remove-Item -Recurse -Force $TempDir
    }
}
