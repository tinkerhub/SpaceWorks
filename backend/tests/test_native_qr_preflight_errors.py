"""Expected preflight refusals preserve Django's native admin response contract."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.db import connection
from django.http import Http404
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.exceptions import PermissionDenied as PolicyPermissionDenied
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.boxes import admin_qr_lifecycle
from apps.boxes.exceptions import Conflict
from apps.boxes.models import QrCode
from apps.inventory.models import InventoryAsset, TrackingMode
from tests.native_qr_preflight_helpers import (
    assert_rebind_error, no_qr_dispatch, qr_persisted_state, record_qr_history,
)
from tests.return_helpers import make_product, make_space, make_user

pytestmark = pytest.mark.django_db


@pytest.fixture
def native_rebind():
    actor = make_user(
        "native-preflight-super", role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE, is_staff=True, is_superuser=True,
    )
    space = make_space("native-preflight-source")
    source = make_product(space, name="Original product")
    target = make_product(space, name="Eligible target", total_quantity=3, available_quantity=3)
    qr = QrCode.objects.create(
        makerspace=space, target_type=QrCode.TargetType.PRODUCT,
        target_id=source.pk, created_by=actor,
    )
    # Another tenant's populated rows make an accidental unscoped write visible.
    other = make_space("native-preflight-other")
    other_product = make_product(
        other, name="Other tenant tool", tracking_mode=TrackingMode.INDIVIDUAL,
        total_quantity=1, available_quantity=1,
    )
    asset = InventoryAsset.objects.create(
        makerspace=other, product=other_product, asset_tag="OTHER-PREFLIGHT-1",
    )
    other_qr = QrCode.objects.create(
        makerspace=other, target_type=QrCode.TargetType.ASSET,
        target_id=asset.pk, created_by=actor,
    )
    for code in (qr, other_qr):
        record_qr_history(code, actor)
    client = Client()
    client.force_login(actor)
    return SimpleNamespace(
        actor=actor, client=client, qr=qr, target=target,
        url=reverse("admin:boxes_qrcode_changelist"),
        payload={"target_type": "product", "product_target": str(target.pk),
                 "new_name": "Must never be saved"},
    )


@pytest.mark.parametrize(("exception_type", "detail", "status", "message"), [
    (ValidationError,
     ["The selected product is no longer eligible.", "Refresh the selection before retrying."],
     200, "The selected product is no longer eligible.; Refresh the selection before retrying."),
    (Conflict, "The QR selection changed; retry the operation.",
     200, "The QR selection changed; retry the operation."),
    (PolicyPermissionDenied, "QR management permission was withdrawn.", 403, None),
    (Http404, "The selected QR is no longer visible.", 404, None),
], ids=["validation-bound-form", "conflict-bound-form", "permission-403", "scoped-404"])
def test_native_preflight_refusal_stops_before_locks_and_dispatch(
    exception_type, detail, status, message, native_rebind, no_qr_dispatch, monkeypatch,
):
    case = native_rebind
    real_preflight = admin_qr_lifecycle.preflight_rebind

    def refuse_after_real_policy(actor, qr_id, payload):
        # Exercise current actor, module, target and RBAC policy first. The only
        # injected behavior is the expected exception at the preflight seam.
        admitted = real_preflight(actor, qr_id, payload)
        assert actor.pk == case.actor.pk
        assert admitted[0].pk == case.qr.pk == qr_id
        assert admitted[1].pk == case.target.pk
        assert payload == {"target_type": "product", "target_id": case.target.pk,
                           "new_name": "Must never be saved"}
        raise exception_type(detail)

    preflight = Mock(side_effect=refuse_after_real_policy)
    monkeypatch.setattr(admin_qr_lifecycle, "preflight_rebind", preflight)
    before = qr_persisted_state()

    with CaptureQueriesContext(connection) as queries:
        response = case.client.post(case.url, {
            "action": "rebind_selected", "index": "0", "apply": "1",
            ACTION_CHECKBOX_NAME: [str(case.qr.pk)], **case.payload,
        })

    preflight.assert_called_once()
    assert response.status_code == status
    assert response.wsgi_request.user.pk == case.actor.pk
    assert not response.wsgi_request.user.is_anonymous
    if status == 200:
        assert_rebind_error(response, case.qr, case.payload, message)
        assert len(no_qr_dispatch) == 1
        assert response.context_data["form"] is no_qr_dispatch[0]
        assert response.context_data["form"].cleaned_data["product_target"].pk == case.target.pk
    assert queries.captured_queries
    assert not any("FOR UPDATE" in query["sql"].upper() for query in queries.captured_queries)
    assert qr_persisted_state() == before
