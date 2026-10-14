"""Settings-free exceptions shared by backup services and host installers."""


class BackupBuildError(RuntimeError):
    """A backup build or verification step refused.

    Must stay importable without configured Django settings: the root host installer
    `scripts/install_producer_capability.py` imports it through `producer_capability`
    under a bare `docker run --entrypoint python`.
    """
