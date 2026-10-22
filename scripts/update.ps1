<#
  Space Works updates are Linux-only: the H1 production updater requires the Linux Compose
  wrapper. On Windows, run  bash scripts/update.sh  from a WSL2 shell with Docker Desktop's
  WSL integration enabled.
#>
# Accepted so existing `update.ps1 -Force` callers get the WSL2 message, not a parameter error.
[CmdletBinding()]
param([switch]$Force)

$ErrorActionPreference = "Stop"
throw "The H1 production updater requires the Linux Compose wrapper. Run scripts/update.sh inside WSL2."
