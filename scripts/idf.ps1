param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$IdfArguments
)

$candidates = @()
if ($env:IDF_TOOLS_PATH) {
    $candidates += Join-Path $env:IDF_TOOLS_PATH "eim_idf.json"
}
$candidates += "C:\Espressif\tools\eim_idf.json"
$configPath = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $configPath) {
    throw "EIM configuration not found. Install ESP-IDF with EIM or set IDF_TOOLS_PATH."
}

$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
$setup = $config.idfInstalled | Where-Object { $_.id -eq $config.idfSelectedId } | Select-Object -First 1
if (-not $setup) {
    throw "The selected ESP-IDF setup is missing from $configPath."
}

. $setup.activationScript
& idf.py @IdfArguments
exit $LASTEXITCODE
