param(
    [string]$ProxyUrl = $env:PAPERNOTE_PIP_PROXY
)

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
$versionText = & $python -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
if ($LASTEXITCODE -ne 0) {
    throw "Python could not be started. Reinstall Python 3.10 or newer."
}
$versionParts = $versionText.Trim().Split('.')
if ([int]$versionParts[0] -lt 3 -or ([int]$versionParts[0] -eq 3 -and [int]$versionParts[1] -lt 10)) {
    throw "PaperNote requires Python 3.10 or newer. Found Python $versionText."
}

$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    & $python -m venv (Join-Path $projectRoot ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Could not create the PaperNote Python environment." }
}

# Never guess a proxy from an open local port. A listening port may belong to
# another program or may not support HTTPS, which leaves a half-installed venv.
# Direct installation is the predictable default; a real proxy must be passed
# explicitly with -ProxyUrl or PAPERNOTE_PIP_PROXY.
$proxyNames = @(
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "all_proxy",
    "PIP_PROXY", "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "PIP_TRUSTED_HOST",
    "PIP_CONFIG_FILE"
)
$savedProxy = @{}
foreach ($name in $proxyNames) {
    $value = [Environment]::GetEnvironmentVariable($name, "Process")
    if ($null -ne $value) { $savedProxy[$name] = $value }
    [Environment]::SetEnvironmentVariable($name, $null, "Process")
}

$pipArgs = @("-m", "pip", "--isolated", "install", "--disable-pip-version-check", "--timeout", "60", "--retries", "2")
if ($ProxyUrl) {
    Write-Output "Using the explicitly configured package proxy: $ProxyUrl"
    $pipArgs += @("--proxy", $ProxyUrl)
} else {
    Write-Output "Installing PaperNote dependencies with a direct connection (proxy settings and pip user configuration are ignored)."
}
$pipArgs += @("-r", (Join-Path $projectRoot "requirements.txt"))
try {
    & $venvPython @pipArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Python dependency installation failed. Check the network, then run setup.bat again. If your network requires a proxy, run: setup.bat -ProxyUrl http://127.0.0.1:PORT"
    }
} finally {
    foreach ($name in $proxyNames) {
        [Environment]::SetEnvironmentVariable($name, $null, "Process")
        if ($savedProxy.ContainsKey($name)) {
            [Environment]::SetEnvironmentVariable($name, $savedProxy[$name], "Process")
        }
    }
}

& $venvPython -c "import fastapi, pydantic, uvicorn; print('Runtime dependency check passed.')"
if ($LASTEXITCODE -ne 0) {
    throw "PaperNote dependencies are incomplete. Run setup.bat again after the network problem is fixed."
}
Write-Output "PaperNote companion environment is ready."
