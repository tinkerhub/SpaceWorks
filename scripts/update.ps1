<# Apply the newest fully-published Space Works release to production Compose. #>
[CmdletBinding()]
param([switch]$Force)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

throw "The H1 production updater requires the Linux Compose wrapper. Run scripts/update.sh inside WSL2."
