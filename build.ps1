param([string]$Port, [switch]$Flash)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'

if (!(Get-Command idf.py -ErrorAction SilentlyContinue)) {
    $exportScript = if ($env:IDF_PATH) { Join-Path $env:IDF_PATH 'export.ps1' } else { $null }
    if (!$exportScript -or !(Test-Path -LiteralPath $exportScript)) {
        throw 'Start an ESP-IDF PowerShell environment so idf.py is available.'
    }
    . $exportScript
}

$privateDir = Join-Path $PSScriptRoot 'private'
$firmwareDir = Join-Path $PSScriptRoot 'firmware'
if (!(Test-Path -LiteralPath (Join-Path $privateDir 'credentials.h'))) {
    python (Join-Path $PSScriptRoot 'provision.py') --build-only
    if ($LASTEXITCODE -ne 0) { throw 'Could not prepare local build credentials.' }
}

$sdkconfig = Join-Path $firmwareDir 'sdkconfig'
$targetConfigured = Test-Path -LiteralPath $sdkconfig
if (!$targetConfigured) {
    if (Test-Path -LiteralPath (Join-Path $firmwareDir 'build')) {
        throw 'A partial build directory exists without sdkconfig. Back it up and clean it before the first target selection.'
    }
    idf.py -C $firmwareDir set-target esp32s3
    if ($LASTEXITCODE -ne 0) { throw 'Could not select the ESP32-S3 target.' }
} elseif (!(Select-String -LiteralPath $sdkconfig -Pattern '^CONFIG_IDF_TARGET="esp32s3"$' -Quiet)) {
    throw 'sdkconfig targets another chip. Back it up and select ESP32-S3 explicitly before building.'
}

idf.py -C $firmwareDir build
if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }

if ($Flash) {
    if (!$Port) { throw 'Specify -Port COMx.' }
    if (!(Test-Path -LiteralPath (Join-Path $privateDir 'provisioned'))) {
        throw 'Real Wi-Fi configuration is required before flashing.'
    }
    if (!(Test-Path -LiteralPath (Join-Path $privateDir 'esp32-original.bin'))) {
        throw 'Back up the board flash locally before flashing.'
    }
    idf.py -C $firmwareDir -p $Port flash
    if ($LASTEXITCODE -ne 0) { throw 'Flash failed.' }
}
