$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $projectRoot

$pythonCandidates = @(
    (Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"),
    (Get-Command py.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
    (Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue)
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }

if (-not $pythonCandidates) {
    throw "Python 3.10 or newer was not found. Install Python and run setup.bat again."
}
$python = @($pythonCandidates)[0]
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    & $python -m venv (Join-Path $projectRoot ".venv")
}
$proxyAvailable = Test-NetConnection -ComputerName "127.0.0.1" -Port 7897 -InformationLevel Quiet -WarningAction SilentlyContinue
$pipArgs = @("-m", "pip", "install", "--disable-pip-version-check", "--timeout", "30")
if ($proxyAvailable) { $pipArgs += @("--proxy", "http://127.0.0.1:7897") }
$pipArgs += @("-r", (Join-Path $projectRoot "requirements.txt"))
& $venvPython @pipArgs
if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed." }
Write-Output "PaperNote companion environment is ready."
