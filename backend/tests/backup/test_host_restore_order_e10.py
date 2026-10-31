"""HOST-ONLY: restored databases receive grants through the privileged bootstrap."""

from pathlib import Path

import pytest

from tests.backup.obsolete_contract_host import assert_privileged_grant_bootstrap


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
RESTORE_SCRIPT = REPOSITORY_ROOT / "scripts" / "restore.sh"
pytestmark = pytest.mark.skipif(
    not RESTORE_SCRIPT.exists(),
    reason="HOST-ONLY: scripts/restore.sh is outside the backend test image",
)


def test_restore_grant_helper_uses_privileged_bootstrap_without_django():
    assert_privileged_grant_bootstrap()
