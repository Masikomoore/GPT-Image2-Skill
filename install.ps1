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
$ZipUrl = "https://github.com/Masikomoore/GPT-Image2-Skill/archive/refs/heads/$Branch.zip"

$ScriptDir = $PSScriptRoot
$TempDir = $null

try {
    if (-not $ScriptDir -or -not (Test-Path (Join-Path $ScriptDir "scripts\setup_skill.py"))) {
        $TempDir = Join-Path ([System.IO.Path]::GetTempPath()) ("gpt-image-skill-" + [System.Guid]::NewGuid().ToString("N"))
        New-Item -ItemType Directory -Path $TempDir | Out-Null
        Write-Host "Downloading GPT-Image2-Skill from $RepoUrl ($Branch)..."
        if (Get-Command git -ErrorAction SilentlyContinue) {
            git clone --depth 1 --branch $Branch $RepoUrl (Join-Path $TempDir "repo") | Out-Null
            $ScriptDir = Join-Path $TempDir "repo"
        } else {
            $ZipPath = Join-Path $TempDir "repo.zip"
            Invoke-WebRequest -Uri $ZipUrl -OutFile $ZipPath
            Expand-Archive -Path $ZipPath -DestinationPath $TempDir -Force
            $Extracted = Get-ChildItem -Path $TempDir -Directory | Select-Object -First 1
            $ScriptDir = $Extracted.FullName
        }
    }

    if (Get-Command uv -ErrorAction SilentlyContinue) {
        try { uv tool install --force $ScriptDir | Out-Null } catch {}
    } else {
        try { python -m pip install --user --quiet -e $ScriptDir | Out-Null } catch {}
    }

    $PyArgs = @((Join-Path $ScriptDir "scripts\setup_skill.py"), "--repo-root", $ScriptDir, "--clients", $Clients)
    if ($AgentMode -or $env:GPT_IMAGE_AGENT_MODE -eq "1" -or $env:GPT_IMAGE_AGENT_MODE -eq "true") {
        $PyArgs += "--agent-mode"
    }
    if ($BaseUrl) { $PyArgs += @("--base-url", $BaseUrl) }
    if ($ApiKey) { $PyArgs += @("--api-key", $ApiKey) }
    if ($EnvPath) { $PyArgs += @("--env-path", $EnvPath) }

    & python @PyArgs
} finally {
    if ($TempDir -and (Test-Path $TempDir)) {
        Remove-Item -Recurse -Force $TempDir
    }
}
