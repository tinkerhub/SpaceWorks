"""Native generation reloads User policy after real Maker/product waits."""
import pytest
from django.contrib.messages import get_messages
from django.db import connection, transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.accounts import rbac
from apps.accounts.models import User
from apps.backup.activation import set_superadmin_access
from apps.backup.custody import with_makerspace_custody_lock
from apps.backup.models import B1ActivationState, MakerspaceArchiveRecipient
from apps.boxes.models import QrCode
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import Makerspace
from apps.operations.services_qr_assets import generate_assets_with_qr
from apps.tenant_migration.gate_runtime import boundary_tenant_write
from tests.box_parent_safety.pg_helpers import (
    assert_maker_mode, blocked_by, maker_lock, workers,
)
from tests.qr_source_safety.http_helpers import (
    closure_lab, empty_product, generation_request,
)
from tests.qr_source_safety.pg_helpers import (
    assert_shared, audit_insert, source_select, table_lock,
)
from tests.qr_source_safety.race_helpers import backend_pid
from tests.qr_source_safety.state_helpers import audit_ids, audits_since, state
from tests.qr_target_safety_helpers import jwt_client, membership

pytestmark = pytest.mark.django_db(transaction=True)
DENIALS = ("inactive", "suspended", "non-superuser", "password-rotation", "hidden-maker")
# Generation owns Maker UPDATE before waiting on Product. A controller holding
# Product cannot hide that Maker: its UPDATE would close a real deadlock cycle.
POLICY_WAITS = [(wait_on, denial) for wait_on in ("maker", "product") for denial in DENIALS
                if wait_on == "maker" or denial != "hidden-maker"]


def mutate_policy(lab, denial):
    if denial == "hidden-maker":
        Makerspace.objects.filter(pk=lab.home.pk).update(superadmin_access_enabled=False)
    else:
        field, value = {"inactive": ("is_active", False), "suspended": ("access_status", "suspended"),
                        "non-superuser": ("is_superuser", False),
                        "password-rotation": ("must_change_password", True)}[denial]
        User.objects.filter(pk=lab.root.pk).update(**{field: value})


@pytest.mark.parametrize("wait_on,denial", POLICY_WAITS,
                         ids=["-".join(case) for case in POLICY_WAITS])
def test_native_generation_refuses_fresh_policy_after_actual_row_wait(closure_lab, denial, wait_on):
    lab = closure_lab
    product = empty_product(lab.home)
    request = generation_request(lab, product, native=True)
    with workers() as start:
        with transaction.atomic():
            model, pk = (Makerspace, lab.home.pk) if wait_on == "maker" else (InventoryProduct, product.pk)
            model.objects.select_for_update().get(pk=pk)
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                owner = cursor.fetchone()[0]
            pending = start(request)
            predicate = maker_lock if wait_on == "maker" else table_lock(model._meta.db_table)
            blocked_by(pending, owner, predicate)
            mutate_policy(lab, denial)
            before = state()
        response = pending.finish()
    # The existing native generation action catches DRF policy refusal as an error
    # message, then returns to its changelist. Preserve that actual HTTP contract.
    assert response.status_code == 302
    messages = list(get_messages(response.wsgi_request))
    assert any(message.level_tag == "error" for message in messages)
    assert not any("Generated " in str(message) for message in messages)
    assert state() == before


def test_native_generation_serializes_before_hide_while_waiting_on_product(closure_lab):
    lab = closure_lab
    product = empty_product(lab.home)
    request = generation_request(lab, product, native=True, count="2")
    # The same verified-recipient row fixture used by test_activation_e6 satisfies
    # the canonical switch's floor; no flag/activation SQL mutation is substituted.
    for number in (1, 2):
        MakerspaceArchiveRecipient.objects.create(
            makerspace=lab.home, public_recipient=f"age1e6recipient{lab.home.pk}{number}",
            fingerprint=f"{lab.home.pk:032x}{number:032x}",
            label=f"Generation custodian {number}", verified_at=timezone.now(),
        )
    before = audit_ids()

    def hide():
        # The supported outer transaction puts Source N on this session, before
        # the canonical custody service takes Maker UPDATE and changes the flag.
        with transaction.atomic(), boundary_tenant_write(lab.home.pk):
            with with_makerspace_custody_lock(lab.home.pk) as custody:
                assert custody.makerspace.superadmin_access_enabled is True
                activation = set_superadmin_access(custody, enabled=False, actor=lab.actor)
        return activation.state

    with workers() as start:
        with transaction.atomic():
            InventoryProduct.objects.select_for_update().get(pk=product.pk)
            controller = backend_pid()
            generation = start(request, pause=audit_insert)
            product_wait = blocked_by(
                generation, controller, table_lock(InventoryProduct._meta.db_table))
            assert product_wait.params == (lab.home.pk, product.pk)
            maker = next(sql for sql in generation.statements if maker_lock(sql))
            assert_maker_mode(maker, "FOR UPDATE")
            assert maker.completed and maker.pid == generation.pid
            assert maker.params == (lab.home.pk,)
            assert generation.statements.index(maker) < generation.statements.index(product_wait)

            hider = start(hide, pause=maker_lock)
            maker_wait = blocked_by(hider, generation.pid, maker_lock)
            assert_maker_mode(maker_wait, "FOR UPDATE")
            assert maker_wait.params == (lab.home.pk,)
            assert len({controller, generation.pid, hider.pid}) == 3
            admitted = [sql for sql in hider.statements if source_select(sql, lab.home.pk)]
            assert admitted and all(sql.completed and sql.pid == hider.pid for sql in admitted)
            assert all(hider.statements.index(sql) < hider.statements.index(maker_wait)
                       for sql in admitted)
            assert_shared(hider.pid, lab.home.pk)
            # Both full SQL/PID edges coexist: Gen -> Controller, Hider -> Gen.
            assert blocked_by(generation, controller,
                              table_lock(InventoryProduct._meta.db_table)) is product_wait
            lab.home.refresh_from_db()
            assert lab.home.superadmin_access_enabled is True
        # Controller COMMIT releases Product. The real generation audit INSERT
        # has completed, but Gen still owns Maker UPDATE until its transaction ends.
        generation.paused()
        assert product_wait.completed
        assert any(sql.completed and audit_insert(sql) for sql in generation.statements)
        assert blocked_by(hider, generation.pid, maker_lock) is maker_wait
        lab.home.refresh_from_db()
        assert lab.home.superadmin_access_enabled is True

        response = generation.finish()
        hider.paused()  # Maker acquired after Gen commit, before any hide write.
        assert maker_wait.completed
        assert response.status_code == 302
        messages = list(get_messages(response.wsgi_request))
        assert [(message.level_tag, str(message)) for message in messages] == [
            ("success", "Generated 2 QR asset(s) for 1 product(s).")]
        lab.home.refresh_from_db()
        assert lab.home.superadmin_access_enabled is True
        product.refresh_from_db()
        assert product.total_quantity == product.available_quantity == product.assets.count() == 2
        assets = list(product.assets.order_by("pk"))
        assert all(asset.makerspace_id == lab.home.pk for asset in assets)
        qrs = list(QrCode.objects.filter(makerspace=lab.home))
        assert len(qrs) == 2
        assert {(qr.target_type, qr.target_id, qr.created_by_id, qr.status) for qr in qrs} == {
            ("asset", asset.pk, lab.root.pk, "active") for asset in assets}
        rows = audits_since(before)
        assert len(rows) == 1
        row = rows[0]
        assert (row.action, row.actor_id, row.makerspace_id, row.target_type, row.target_id, row.meta) == (
            "asset_units.generated", lab.root.pk, lab.home.pk, "inventory.inventoryproduct",
            str(product.pk), {"count": 2})
        assert hider.finish() == B1ActivationState.State.OFF_PENDING

    lab.home.refresh_from_db()
    assert lab.home.superadmin_access_enabled is False
    assert B1ActivationState.objects.get(makerspace=lab.home).state == B1ActivationState.State.OFF_PENDING
    rows = audits_since(before)
    assert len(rows) == 2
    assert (rows[1].action, rows[1].actor_id, rows[1].makerspace_id, rows[1].meta) == (
        "makerspace.superadmin_access_changed", lab.actor.pk, lab.home.pk,
        {"enabled": False, "activation_before": "on", "activation_after": "off_pending"})
    # A hidden changelist can redirect without selecting an action. Exercise the
    # actual native service policy explicitly, with the original actor/product.
    hidden = state()
    with pytest.raises(PermissionDenied):
        generate_assets_with_qr(lab.root, product, {"count": 1}, native=True)
    assert state() == hidden


def test_api_generation_hidden_maker_explicit_membership_keeps_manage_qr_authority(closure_lab):
    lab = closure_lab
    membership(lab.root, lab.home, "inventory_manager")
    Makerspace.objects.filter(pk=lab.home.pk).update(superadmin_access_enabled=False)
    assert rbac.can(lab.root, rbac.Action.MANAGE_QR, lab.home.pk)
    lab.api = jwt_client(lab.root)
    product = empty_product(lab.home)
    before = audit_ids()
    response = generation_request(lab, product)()
    assert response.status_code == 201, response.data
    product.refresh_from_db()
    assert product.total_quantity == product.available_quantity == product.assets.count() == 1
    qr = QrCode.objects.get(target_id=product.assets.get().pk, target_type="asset")
    assert qr.created_by_id == lab.root.pk and qr.makerspace_id == lab.home.pk
    rows = audits_since(before)
    assert len(rows) == 1
    assert (rows[0].action, rows[0].actor_id, rows[0].meta) == (
        "asset_units.generated", lab.root.pk, {"count": 1})


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("policy", ["module-off", "quota", "quantity-stock"])
def test_actual_generation_preserves_module_quota_and_quantity_refusals(closure_lab, native, policy):
    lab = closure_lab
    product = empty_product(lab.home)
    if policy == "module-off":
        Makerspace.objects.filter(pk=lab.home.pk).update(
            enabled_modules=[key for key in lab.home.enabled_modules if key != "asset_units"])
    elif policy == "quota":
        Makerspace.objects.filter(pk=lab.home.pk).update(resource_limit_overrides={"assets": 0})
    else:
        InventoryProduct.objects.filter(pk=product.pk).update(
            tracking_mode="quantity", total_quantity=1, available_quantity=1)
    before = state()
    response = generation_request(lab, product, native=native)()
    assert response.status_code == (302 if native else 409 if policy == "quantity-stock" else 400)
    if native:
        assert any(message.level_tag == "error" for message in get_messages(response.wsgi_request))
    else:
        assert ("module" if policy == "module-off" else "limit" if policy == "quota" else "code") in response.data
    assert state() == before


@pytest.mark.parametrize("native", [False, True])
def test_generation_reuses_missing_qr_before_adding_units_and_updates_quantities(closure_lab, native):
    lab = closure_lab
    from tests.qr_target_safety_helpers import target
    asset = target(lab.home, "asset")
    product = asset.product
    request = generation_request(lab, product, native=native, count="2" if native else 2)
    assert request().status_code == (302 if native else 201)
    product.refresh_from_db()
    assert product.assets.count() == product.total_quantity == product.available_quantity == 2
    assert QrCode.objects.filter(makerspace=lab.home, target_type="asset",
                                 target_id__in=product.assets.values("pk")).count() == 2
