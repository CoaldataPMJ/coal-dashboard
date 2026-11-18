param([string]$Source = "")
$ErrorActionPreference = "Stop"
$CoalArguments = @((Join-Path $PSScriptRoot "extract_dashboard_data.py"), "--output-dir", $PSScriptRoot)
if ($Source) { $CoalArguments += @("--source", $Source) }
if (Get-Command python -ErrorAction SilentlyContinue) {
    & python @CoalArguments
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 @CoalArguments
} else {
    throw "Python 3.9+ is required."
}
if ($LASTEXITCODE -ne 0) { throw "Data extraction failed. See the message above." }
Write-Output "Local data.js updated. Commit data.js to GitHub to refresh the website."
