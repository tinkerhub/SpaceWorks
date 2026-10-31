"""Fresh policy after a genuine QR wait, through HTTP and unmodified admission."""
import pytest
from django.db import connection, transaction
from rest_framework.exceptions import PermissionDenied

from apps.accounts import rbac
from apps.accounts.models import User
from apps.boxes.models import QrCode
from apps.boxes.qr_admission import current_qr_actor
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from apps.operations.models import QrPrintBatchItem
from apps.organizations.models import OrganizationMembership
from tests.box_parent_safety.pg_helpers import blocked_by, workers
from tests.qr_print_race_safety.helpers import (
    add_http, assert_event, assert_order, assert_qr_scope, events, evidence,
    frozen, item_write, lab, prepare, qr_lock, record_protocol, row, state,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def policy_lab(lab):
    # The global Member identity is REQUESTER in this schema. Neither it nor
    # CUSTOM's legacy fallback can confer QR authority after withdrawal.
    assert lab.actor.role == User.Role.REQUESTER
    assert not lab.actor.is_superuser and not lab.actor.is_staff
    assert not OrganizationMembership.objects.filter(user=lab.actor).exists()
    membership = MakerspaceMembership.objects.get(user=lab.actor)
    role = MakerspaceRole.objects.create(
        makerspace=lab.home, name="Print policy", slug="print-policy",
        granted_actions=[rbac.Action.MANAGE_QR],
    )
    membership.role = MakerspaceMembership.Role.CUSTOM
    membership.assigned_role = role
    membership.save(update_fields=["role", "assigned_role"])
    lab.membership, lab.role = membership, role
    assert current_qr_actor(lab.actor).pk == lab.actor.pk
    assert rbac.can(lab.actor, rbac.Action.MANAGE_QR, lab.home.pk)
    return lab


def policy_state():
    # state() already includes full item/QR/domain/counter/scan/audit/MAC rows.
    # Add every policy column, retaining bytes from BinaryField memoryviews.
    return {
        **state(),
        **frozen({model._meta.label_lower: list(model.objects.order_by("pk").values())
                  for model in (User, MakerspaceMembership, MakerspaceRole,
                                OrganizationMembership)}),
    }


def prepare_item(lab, kind, existing):
    case = prepare(lab, kind)
    if existing:
        response = add_http(lab, case, label_text="Original label", sort_order=4)
        assert response.status_code == 201, response.data
        case.item_before = row(QrPrintBatchItem, response.data["id"])
    else:
        assert not QrPrintBatchItem.objects.filter(batch=lab.batch, qr_code=case.qr).exists()
        case.item_before = None
    return case


def assert_no_dml(worker):
    # Stronger than checking row equality: even rolled-back domain/module/audit
    # writes would violate admission. Framework and audit code stay real.
    assert not [s for s in worker.statements
                if s.sql.lstrip().upper().startswith(("INSERT ", "UPDATE ", "DELETE "))]


def observe_wait(api, owner, lab, case, record_property):
    pending = blocked_by(api, owner, qr_lock)
    assert pending.sql.rstrip().endswith("FOR UPDATE"), pending
    assert_qr_scope(pending, lab, case)
    # Require the exact singleton edge, not just an eventual response or a timer.
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_blocking_pids(%s)", [api.pid])
        assert cursor.fetchone()[0] == [owner]
    evidence(record_property, pending, owner)
    prior = api.statements[:api.statements.index(pending)]
    assert any(s.completed and 'FROM "accounts_user"' in s.sql
               and lab.actor.pk in s.params for s in prior)
    assert any(s.completed and 'FROM "makerspaces_makerspacemembership"' in s.sql
               and '"makerspaces_makerspacerole"' in s.sql
               and '"granted_actions"' in s.sql for s in prior)
    assert_no_dml(api)
    assert not pending.completed
    return pending


def controller_lock(case):
    QrCode.objects.select_for_update().get(pk=case.qr.pk, makerspace_id=case.qr.makerspace_id)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_backend_pid()")
        return cursor.fetchone()[0]


def assert_fresh_sql(api, lab, *, role_checked):
    index = next(i for i, s in enumerate(api.statements) if qr_lock(s))
    fresh = [(i, s) for i, s in enumerate(api.statements)
             if i > index and s.completed and 'FROM "accounts_user"' in s.sql
             and lab.actor.pk in s.params]
    assert fresh, api.statements
    if role_checked:
        assert any(s.completed and 'FROM "makerspaces_makerspacemembership"' in s.sql
                   and '"makerspaces_makerspacerole"' in s.sql
                   and '"granted_actions"' in s.sql
                   for s in api.statements[fresh[0][0] + 1:])


@pytest.mark.parametrize("kind", ["product", "asset"])
@pytest.mark.parametrize("existing", [False, True], ids=["new-item", "existing-item"])
@pytest.mark.parametrize("withdrawal", ["inactive", "suspended", "role"])
def test_policy_withdrawn_during_real_qr_wait_refuses_without_any_writes(
    policy_lab, kind, existing, withdrawal, record_property,
):
    lab = policy_lab
    case = prepare_item(lab, kind, existing)
    with workers() as start:
        with transaction.atomic():
            owner = controller_lock(case)
            api = start(lambda: add_http(lab, case, label_text="Forbidden change", sort_order=19))
            pending = observe_wait(api, owner, lab, case, record_property)
            # Only change policy AFTER pg_blocking_pids proves the QR wait.
            if withdrawal == "inactive":
                User.objects.filter(pk=lab.actor.pk).update(is_active=False)
            elif withdrawal == "suspended":
                User.objects.filter(pk=lab.actor.pk).update(access_status=User.AccessStatus.SUSPENDED)
            else:
                MakerspaceRole.objects.filter(pk=lab.role.pk).update(granted_actions=[])
            fresh = User.objects.get(pk=lab.actor.pk)
            membership = MakerspaceMembership.objects.get(pk=lab.membership.pk)
            assert membership.assigned_role_id == lab.role.pk
            assert membership.role == MakerspaceMembership.Role.CUSTOM
            assert fresh.role == User.Role.REQUESTER and not fresh.is_superuser
            assert not OrganizationMembership.objects.filter(user=fresh).exists()
            if withdrawal == "role":
                assert current_qr_actor(lab.actor).pk == fresh.pk
                assert not rbac.can(fresh, rbac.Action.MANAGE_QR, lab.home.pk)
            else:
                with pytest.raises(PermissionDenied):
                    current_qr_actor(lab.actor)
            # Freeze the FULL winner state while Controller still owns QR. A
            # post-commit snapshot could accidentally include buggy API writes.
            expected = policy_state()
            assert not pending.completed
            assert_no_dml(api)
        response = api.finish()  # Controller COMMIT releases QR and policy together.
    assert response.status_code == 403, response.data
    assert response.data["detail"].code == "permission_denied"
    assert_order(api, lab, case, wrote=False)
    assert_fresh_sql(api, lab, role_checked=withdrawal == "role")
    assert_no_dml(api)
    record_protocol(record_property, api)
    assert policy_state() == expected
    if withdrawal == "role":
        assert not rbac.can(current_qr_actor(lab.actor), rbac.Action.MANAGE_QR, lab.home.pk)


@pytest.mark.parametrize("kind", ["product", "asset"])
@pytest.mark.parametrize("existing", [False, True], ids=["new-item", "existing-item"])
def test_grant_retained_during_real_qr_wait_writes_correct_snapshot_and_actor_audit(
    policy_lab, kind, existing, record_property,
):
    lab = policy_lab
    case = prepare_item(lab, kind, existing)
    with workers() as start:
        with transaction.atomic():
            owner = controller_lock(case)
            api = start(lambda: add_http(lab, case, label_text="Admitted change", sort_order=19))
            pending = observe_wait(api, owner, lab, case, record_property)
            User.objects.filter(pk=lab.actor.pk).update(display_name="Fresh retained principal")
            MakerspaceRole.objects.filter(pk=lab.role.pk).update(
                granted_actions=[rbac.Action.MANAGE_QR, rbac.Action.VIEW_INVENTORY],
            )
            fresh = current_qr_actor(lab.actor)
            assert fresh.display_name == "Fresh retained principal"
            assert rbac.can(fresh, rbac.Action.MANAGE_QR, lab.home.pk)
            expected = policy_state()
            assert not pending.completed
            assert_no_dml(api)
        response = api.finish()
    assert response.status_code == 201, response.data
    item = QrPrintBatchItem.objects.get(pk=response.data["id"])
    expected_item = {
        "id": case.item_before["id"] if existing else item.pk,
        "batch_id": lab.batch.pk, "qr_code_id": case.qr.pk,
        "target_type": kind, "target_id": case.obj.pk,
        "label_text": "Admitted change", "sort_order": 19,
    }
    assert row(QrPrintBatchItem, item.pk) == expected_item
    before_audit = expected["audit.auditlog"]
    delta = events().exclude(pk__in=[entry["id"] for entry in before_audit])
    assert delta.count() == 1
    event = delta.get()
    action = "qr_print_batch_item.updated" if existing else "qr_print_batch_item.created"
    assert_event(event, lab, item, action)
    assert event.row_mac is not None and len(bytes(event.row_mac)) == 32
    # Allow only the exact full item row and one real actor audit append.
    expected["operations.qrprintbatchitem"] = [expected_item]
    expected["audit.auditlog"] = before_audit + [row(type(event), event.pk)]
    assert policy_state() == expected
    assert len([s for s in api.statements if item_write(s)]) == 1
    assert_order(api, lab, case, wrote=True)
    assert_fresh_sql(api, lab, role_checked=True)
    record_protocol(record_property, api)
