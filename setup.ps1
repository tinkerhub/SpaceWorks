<#
  Space Works - first-run setup is Linux-only.
  Production host orchestration needs Linux flock, AF_UNIX sockets and root-owned-file trust
  semantics, which native Windows (PowerShell or Git Bash) does not provide. On Windows, open a
  WSL2 shell with Docker Desktop's WSL integration enabled and run:  bash setup.sh
#>
$ErrorActionPreference = "Stop"
throw "Production host orchestration requires Linux flock and Unix-socket semantics. Run 'bash setup.sh' inside WSL2 instead."
