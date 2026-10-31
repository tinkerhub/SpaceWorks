"""Settings-free FULL capture admission for the host-provisioned OCI identity."""

import os
import re

from apps.backup.errors import BackupBuildError


class RuntimeImageIdentityError(BackupBuildError):
    """A signed FULL capture requires an actual host-provisioned RepoDigest."""

    def __init__(self, reason):
        self.reason = reason
        super().__init__(
            f"{reason}: Signed FULL backup requires SPACEWORKS_OCI_DIGEST from the actual "
            "published/pulled backend image. On the host run python3 "
            "scripts/provision-runtime-image.py --env-file <static-env> --image <repository:tag> "
            "and refresh trusted Compose records, then recreate application containers with "
            "--pull never. Source builds must first publish and pull their backend image; "
            "an image config Id or tag cannot substitute for RepoDigest."
        )


def require_runtime_image_digest():
    digest = os.environ.get("SPACEWORKS_OCI_DIGEST", "")
    if not digest:
        raise RuntimeImageIdentityError("runtime_image_digest_missing")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise RuntimeImageIdentityError("runtime_image_digest_invalid")
    return digest
