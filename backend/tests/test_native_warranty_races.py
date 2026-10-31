"""Frozen native Warranty POST vs canonical transfer, with actual PostgreSQL waits."""
import pytest
from django.db import connection
from django.urls import reverse

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.makerspaces.models import Makerspace
from apps.warranty.models import Warranty
from tests.document_safety.helpers import asset, machine
from tests.document_safety.pg_helpers import (
    assert_maker_key_share_compatible, assert_no_maker_upgrade, race, statement,
)
from tests.document_safety.test_transfer_concurrency import transfer
from tests.native_warranty_race_helpers import (
    EDIT, assert_documents_unchanged, assert_move_result, assert_native_audit,
    assert_native_lock_order, form, frozen_source_wait, locked_host, locked_maker,
    native_case, source_locks,
)
from tests.qr_target_safety_helpers import snapshot
from tests.tenant_migration.source_gate_helpers import close_gate

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("move_first", [True, False])
def test_actual_native_change_vs_canonical_move_both_winners(move_first, monkeypatch, settings):
    case = native_case(monkeypatch, settings, documents=True)
    host, qr, product, move = transfer(case)
    url, data = form(case, **EDIT)
    original = Warranty.objects.filter(pk=case.target.pk).values().get()
    baseline = {}

    def post():
        baseline["locks"] = source_locks()
        return case.native.post(url, data)

    def while_move_uncommitted(pids, captured):
        assert_maker_key_share_compatible(pids, captured)
        extra = source_locks() - baseline["locks"]
        assert any(tenant == case.home.pk for _, tenant, _ in extra), extra
        assert all(tenant in {0, case.home.pk} for _, tenant, _ in extra), extra
        # Native passed Maker NO KEY UPDATE and is genuinely waiting on old-tenant host.
        assert_native_lock_order(case, captured, "second", complete=False)
        queries = captured["second"]
        snapshot_at = next(i for i, (sql, _) in enumerate(queries)
                           if statement("warranty_warranty", "SELECT")(sql) and "FOR UPDATE" not in sql)
        maker_at = next(i for i, (sql, _) in enumerate(queries)
                        if statement("makerspaces_makerspace", "FOR NO KEY UPDATE")(sql))
        assert snapshot_at < maker_at
        # MVCC still exposes the source snapshot while the move owns uncommitted rows.
        assert Warranty.objects.filter(pk=case.target.pk).values().get() == original

    if move_first:
        moved, native, captured, pids, waited = race(
            move, post,
            pause_after=lambda sql: sql.startswith('INSERT INTO "operations_inventoryadjustment"'),
            table=host._meta.db_table, clause="FOR UPDATE",
            before_release=while_move_uncommitted,
        )
        assert (moved.status_code, native.status_code) == (200, 404)
        native_worker = "second"
        assert_native_lock_order(case, captured, native_worker, complete=False)
        assert not any(sql.startswith('UPDATE "warranty_warranty"') for sql, _ in captured[native_worker])
        assert not AuditLog.objects.filter(action__startswith="control.object_").exists()
    else:
        native, moved, captured, pids, waited = race(
            post, move, pause_after=statement(host._meta.db_table, "FOR UPDATE"),
            table=host._meta.db_table, clause="FOR UPDATE",
        )
        assert (native.status_code, moved.status_code) == (302, 200)
        native_worker = "first"
        assert_native_lock_order(case, captured, native_worker)
    assert pids["first"] != pids["second"] and "FOR UPDATE" in waited
    moved_audit = assert_move_result(case, host, qr, product)
    if move_first:
        for name in EDIT:
            assert getattr(case.target, name) == original[name]
    else:
        for name, expected in EDIT.items():
            assert str(getattr(case.target, name)) == expected
        assert assert_native_audit(case).pk < moved_audit.pk
    assert_documents_unchanged(case)


@pytest.mark.parametrize("kind", ["asset", "machine"])
@pytest.mark.parametrize("policy", ["revoked", "hidden", "module-disabled"])
def test_native_rechecks_fresh_admission_after_real_maker_wait(kind, policy, monkeypatch, settings):
    case = native_case(monkeypatch, settings, kind, documents=True)
    url, data = form(case, **EDIT)
    before = snapshot(Warranty)

    def change_policy():
        if policy == "revoked":
            User.objects.filter(pk=case.root.pk).update(is_superuser=False)
        elif policy == "hidden":
            Makerspace.objects.filter(pk=case.home.pk).update(superadmin_access_enabled=False)
        else:
            modules = set(case.home.enabled_modules) - {case.module_key}
            Makerspace.objects.filter(pk=case.home.pk).update(enabled_modules=sorted(modules))

    _, response, captured, _, _ = race(
        locked_maker(case, change_policy), lambda: case.native.post(url, data),
        pause_after=statement("makerspaces_makerspace", "FOR NO KEY UPDATE"),
        table="makerspaces_makerspace", clause="FOR NO KEY UPDATE",
    )
    assert response.status_code == (404 if policy == "hidden" else 403)
    assert_no_maker_upgrade(captured, "second")
    assert snapshot(Warranty) == before
    assert_documents_unchanged(case)


@pytest.mark.parametrize("kind", ["asset", "machine"])
def test_valid_native_add_locks_host_before_model_validation(kind, monkeypatch, settings):
    case = native_case(monkeypatch, settings, kind)
    case.target.delete()  # No documents: no storage lifecycle is bypassed.
    url, data = form(case, add=True, **EDIT)
    _, response, captured, _, _ = race(
        locked_host(case), lambda: case.native.post(url, data),
        pause_after=statement(case.host._meta.db_table, "FOR UPDATE"),
        table=case.host._meta.db_table, clause="FOR UPDATE",
    )
    assert response.status_code == 302
    assert_native_lock_order(case, captured, "second", complete=False)
    obj = Warranty.objects.get()
    assert obj.makerspace_id == case.home.pk and getattr(obj, f"{kind}_id") == case.host.pk
    for name, expected in EDIT.items():
        assert str(getattr(obj, name)) == expected
    obj.full_clean()
    assert assert_native_audit(case, created=True).target_id == str(obj.pk)
    assert_documents_unchanged(case)


@pytest.mark.parametrize("kind", ["asset", "machine"])
def test_native_add_requires_same_makerspace_host(kind, monkeypatch, settings):
    case = native_case(monkeypatch, settings, kind)
    case.target.delete()
    foreign = (asset if kind == "asset" else machine)(case.other)
    url, data = form(case, add=True, **{kind: foreign.pk}, **EDIT)
    before = snapshot(Warranty)
    response = case.native.post(url, data)
    assert response.status_code == 200
    assert kind in response.context["adminform"].form.errors
    assert snapshot(Warranty) == before
    assert_documents_unchanged(case)


@pytest.mark.parametrize("bad", ["maker", "asset", "missing-host", "both-hosts", "date"])
def test_malformed_native_add_is_form_error_not_server_error(bad, monkeypatch, settings):
    case = native_case(monkeypatch, settings)
    case.target.delete()
    url, data = form(case, add=True, **EDIT)
    if bad == "maker":
        data["makerspace"] = "not-an-integer"
    elif bad == "asset":
        data["asset"] = "not-an-integer"
    elif bad == "missing-host":
        data["asset"] = ""
    elif bad == "both-hosts":
        data["machine"] = machine(case.home).pk
    else:
        data["purchased_on"] = "not-a-date"
    before = snapshot(Warranty)
    response = case.native.post(url, data)
    assert response.status_code == 200 and response.context["adminform"].form.errors
    assert snapshot(Warranty) == before
    assert_documents_unchanged(case)


@pytest.mark.parametrize("kind", ["asset", "machine"])
def test_crafted_native_save_as_new_cannot_bypass_change_admission(kind, monkeypatch, settings):
    case = native_case(monkeypatch, settings, kind, documents=True)
    url, data = form(case, _saveasnew="Save as new", makerspace=case.other.pk, **EDIT)
    before = snapshot(Warranty)
    assert case.native.post(url, data).status_code == 403
    assert snapshot(Warranty) == before
    assert_documents_unchanged(case)


def test_nonexistent_native_change_post_is_404(monkeypatch, settings):
    case = native_case(monkeypatch, settings)
    url, data = form(case, **EDIT)
    case.target.delete()
    before = snapshot(Warranty)
    assert case.native.post(url, data).status_code == 404
    assert snapshot(Warranty) == before


@pytest.mark.parametrize("kind", ["asset", "machine"])
def test_warranty_disappearing_after_snapshot_returns_404_after_host_wait(kind, monkeypatch, settings):
    case = native_case(monkeypatch, settings, kind)
    url, data = form(case, **EDIT)
    _, response, captured, _, _ = race(
        locked_host(case, lambda: Warranty.objects.filter(pk=case.target.pk).delete()),
        lambda: case.native.post(url, data),
        pause_after=statement(case.host._meta.db_table, "FOR UPDATE"),
        table=case.host._meta.db_table, clause="FOR UPDATE",
    )
    assert response.status_code == 404 and not Warranty.objects.exists()
    assert_native_lock_order(case, captured, "second")
    assert not AuditLog.objects.filter(action__startswith="control.object_").exists()
    assert_documents_unchanged(case)


@pytest.mark.parametrize("kind", ["asset", "machine"])
def test_actual_native_delete_preserves_nonatomic_initial_lookup(kind, monkeypatch, settings):
    case = native_case(monkeypatch, settings, kind)
    assert not case.target.documents.exists()
    lookups = []

    def capture(execute, sql, params, many, context):
        if statement("warranty_warranty", "SELECT")(sql):
            lookups.append((connection.in_atomic_block, sql))
        return execute(sql, params, many, context)

    pk = case.target.pk
    with connection.execute_wrapper(capture):
        response = case.native.post(reverse("admin:warranty_warranty_delete", args=[pk]), {"post": "yes"})
    assert response.status_code == 302  # Client propagates TransactionManagementError if introduced.
    assert lookups and lookups[0][0] is False
    assert all("FOR UPDATE" not in sql and "FOR NO KEY UPDATE" not in sql for _, sql in lookups)
    assert not Warranty.objects.filter(pk=pk).exists()
    row = AuditLog.objects.get(action="control.object_deleted")
    assert (row.makerspace_id, row.actor_id, row.target_id) == (case.home.pk, case.root.pk, str(pk))
    assert not AuditLog.objects.filter(makerspace=case.other, action__startswith="control.object_").exists()
    assert_documents_unchanged(case)


@pytest.mark.parametrize("kind", ["asset", "machine"])
@pytest.mark.parametrize("add", [False, True])
def test_frozen_source_native_admission_refuses_before_mutation(kind, add, monkeypatch, settings):
    case = native_case(monkeypatch, settings, kind)
    if add:
        case.target.delete()
    url, data = form(case, add=add, **EDIT)
    close_gate(case.home, case.root)
    before = snapshot(Warranty)
    assert case.native.post(url, data).status_code == 423
    assert snapshot(Warranty) == before
    assert_documents_unchanged(case)


@pytest.mark.parametrize("kind", ["asset", "machine"])
def test_native_source_refusal_after_observed_exclusive_boundary_wait(kind, monkeypatch, settings):
    case = native_case(monkeypatch, settings, kind, documents=True)
    url, data = form(case, **EDIT)
    before = snapshot(Warranty)
    response, captured, pids, waited = frozen_source_wait(case, url, data)
    assert response.status_code == 423 and len(set(pids)) == 3
    assert "pg_advisory_xact_lock_shared" in waited
    assert not any("FOR UPDATE" in sql or "FOR NO KEY UPDATE" in sql for sql, _ in captured)
    assert snapshot(Warranty) == before
    assert_documents_unchanged(case)
