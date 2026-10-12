$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

python -m PyInstaller --noconfirm --clean "PDF-Merge-Guard.spec"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

Write-Host "Built: $projectRoot\dist\PDF Merge Guard.exe"

