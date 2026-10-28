"""QR revoke must run its row lock inside a transaction.

`locked_qr_for_action` uses select_for_update. Without ATOMIC_REQUESTS a view runs in
autocommit, where Django raises TransactionManagementError -- so every revoke was a 500.
The ordinary `django_db` mark wraps each test in a transaction and hides that, which is
why this file runs with `transaction=True`.
"""

import pytest

from apps.boxes.models import QrCode
from tests.return_helpers import authenticated_client, make_member, make_space

pytestmark = pytest.mark.django_db(transaction=True)


def test_revoke_succeeds_under_autocommit():
    makerspace = make_space("qr-revoke-autocommit")
    admin = make_member("qr-revoke-autocommit-admin", makerspace)
    client = authenticated_client(admin)
    created = client.post(
        "/api/v1/admin/qr/boxes",
        {"makerspace_id": makerspace.id, "label": "Autocommit Bin"},
        format="json",
    )
    assert created.status_code == 201
    qr = QrCode.objects.get(makerspace=makerspace, target_type=QrCode.TargetType.BOX)

    response = client.post(f"/api/v1/admin/qr/{qr.id}/revoke")

    assert response.status_code == 200
    assert response.json()["status"] == QrCode.Status.REVOKED
    qr.refresh_from_db()
    assert qr.status == QrCode.Status.REVOKED
