param(
    [string]$ProjectPath = "."
)

$ErrorActionPreference = "Stop"

$ProjectPath = (Resolve-Path $ProjectPath).Path
Set-Location $ProjectPath

Write-Host ""
Write-Host "RareIQ Git Setup" -ForegroundColor Cyan
Write-Host "Project: $ProjectPath" -ForegroundColor DarkGray
Write-Host ""

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git is not installed or is not available in PATH. Install Git for Windows, then run this script again."
}

if (-not (Test-Path "app.py") -and -not (Test-Path "rareiq")) {
    throw "This does not look like the RareIQ project root. Run the script from the folder containing app.py and the rareiq folder."
}

$gitignore = @'
# Python
__pycache__/
*.py[cod]
*.pyd
*.so
.Python
.venv/
venv/
env/
ENV/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/

# IDE / OS
.vscode/
.idea/
.DS_Store
Thumbs.db
desktop.ini

# Secrets and local configuration
rareiq_secrets.json
.env
.env.*
*.key
*.pem
storage_config.local.json

# Runtime databases and indexes
*.db
*.db-shm
*.db-wal
*.sqlite
*.sqlite3
embeddings/
indexes/
index/
vector_store/
faiss/
chroma/
cache/
.cache/

# Generated and downloaded card assets
captures/
downloads/
exports/
reports/
diagnostics/
logs/
artwork/
images/
card_images/
catalogs/
datasets/
models/
weights/

# Large data formats
*.npy
*.npz
*.faiss
*.index
*.bin
*.onnx
*.pt
*.pth
*.safetensors
*.parquet

# Archives and installers
*.zip
*.7z
*.rar
*.tar
*.gz
*.msi
*.exe

# Temporary files
*.tmp
*.temp
*.bak
*.old
~$*
'@

$gitignorePath = Join-Path $ProjectPath ".gitignore"
if (Test-Path $gitignorePath) {
    $existing = Get-Content $gitignorePath -Raw
    if ($existing -notmatch "RareIQ") {
        Add-Content $gitignorePath "`n# RareIQ local/runtime exclusions`n$gitignore"
    }
} else {
    Set-Content -Path $gitignorePath -Value "# RareIQ local/runtime exclusions`n$gitignore" -Encoding UTF8
}

if (-not (Test-Path ".git")) {
    git init
}

git config core.autocrlf true

$userName = git config user.name
$userEmail = git config user.email

if (-not $userName) {
    git config user.name "Jon"
}
if (-not $userEmail) {
    git config user.email "jon@rareiq.local"
}

# Prevent accidental tracking of local files if they were previously added.
$localPatterns = @(
    ".venv",
    "rareiq_secrets.json",
    "cache",
    "captures",
    "downloads",
    "exports",
    "diagnostics",
    "logs"
)

foreach ($pattern in $localPatterns) {
    git rm -r --cached --ignore-unmatch $pattern 2>$null | Out-Null
}

git add .gitignore
git add .

$hasCommit = $false
git rev-parse --verify HEAD 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
    $hasCommit = $true
}

if (-not $hasCommit) {
    git commit -m "chore: establish RareIQ baseline"
} else {
    $changes = git status --porcelain
    if ($changes) {
        git commit -m "chore: checkpoint current RareIQ baseline"
    }
}

$branch = "sprint/6.4-recognition-pipeline"
$branchExists = git branch --list $branch

if ($branchExists) {
    git switch $branch
} else {
    git switch -c $branch
}

Write-Host ""
Write-Host "RareIQ source control is ready." -ForegroundColor Green
Write-Host "Current branch: $branch" -ForegroundColor Green
Write-Host ""
Write-Host "Useful commands:" -ForegroundColor Cyan
Write-Host "  git status"
Write-Host "  git add ."
Write-Host '  git commit -m "feat: describe the change"'
Write-Host "  git log --oneline --decorate -10"
Write-Host ""
Write-Host "To return to the baseline later:" -ForegroundColor Yellow
Write-Host "  git switch master"
Write-Host "or, depending on your default branch:"
Write-Host "  git switch main"
Write-Host ""
