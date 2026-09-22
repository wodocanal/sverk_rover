$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not $env:IDF_EXPORT) {
    $env:IDF_EXPORT = Join-Path $HOME "esp\esp-idf\export.ps1"
}

if (Test-Path $env:IDF_EXPORT) {
    . $env:IDF_EXPORT
}

$Python = if ($env:PYTHON) { $env:PYTHON } else { "python" }
& $Python (Join-Path $ScriptDir "flash_waveshare_audio.py") @args
exit $LASTEXITCODE
