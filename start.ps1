$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
Set-Location -LiteralPath $projectRoot

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker Desktop is not installed or docker is not in PATH. Install Docker Desktop, restart PowerShell, and run this script again."
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env. Add DEEPSEEK_API_KEY and replace SESSION_SECRET, then run .\start.ps1 again." -ForegroundColor Yellow
    exit 1
}

$settings = Get-Content ".env" -Raw
if ($settings -notmatch "(?m)^DEEPSEEK_API_KEY=.+$") {
    throw "DEEPSEEK_API_KEY is empty in .env. Add the key before starting."
}
if ($settings -match "(?m)^SESSION_SECRET=replace-with-") {
    throw "Replace SESSION_SECRET in .env with at least 32 random characters."
}

# Docker BuildKit on Windows can reject non-ASCII build paths in gRPC headers.
if ($projectRoot -match '[^\x00-\x7F]') {
    $drive = "R:"
    $mapping = (& subst | Where-Object { $_ -like "R:\:*" } | Select-Object -First 1)
    if ($mapping) {
        $mappedTarget = ($mapping -split '=>', 2)[1].Trim().TrimEnd('\')
        if ($mappedTarget -ne $projectRoot.TrimEnd('\')) {
            throw "$drive is already in use. Remove that mapping or move the project to an ASCII-only path."
        }
    } else {
        subst $drive $projectRoot
    }
    Set-Location "$drive\"
}

docker compose up --build
