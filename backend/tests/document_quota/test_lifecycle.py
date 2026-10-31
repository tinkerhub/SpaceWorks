"""Finite debits, immutable provenance and capacity through actual staff APIs."""
import pytest
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.backup.models_host_identity import DeploymentDatabaseIdentity
from apps.makerspaces import limits
from tests.document_safety.helpers import (
    assert_storage_boundary, cap, finalize, lab, snapshot, usage,
)
from tests.document_quota.helpers import (
    KINDS, delete, expected_meta, releases, upload,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("kind", KINDS)
def test_real_debit_is_on_added_event_and_delete_releases_original_pk_once(
    kind, monkeypatch, settings,
):
    case = lab(monkeypatch, settings, kind)
    cap(case, 1000000, used=900)
    before = AuditLog.objects.count()
    row, charge, body = upload(case, boundary=lambda: assert_storage_boundary(case))
    pk = row.pk
    assert charge.meta == expected_meta(case, row, len(body))
    assert charge.actor_id == case.actor.pk
    assert AuditLog.objects.count() == before + 1  # No second charge event.
    assert usage(case) == 900 + len(body)
    calls, state = list(case.store.calls), snapshot(case)
    retry = finalize(case, row.object_key)
    assert retry.status_code == 201 and retry.data["id"] == pk
    assert snapshot(case) == state and case.store.calls == calls

    assert delete(case, row).status_code == 204
    assert not case.model.objects.filter(pk=pk).exists()
    assert not case.store.versions.get(row.object_key)
    assert usage(case) == 900
    release = releases(case).get()
    assert (release.target_type, release.target_id) == (row._meta.label_lower, str(pk))
    assert release.actor_id is None
    assert release.meta == charge.meta | {"charge_event_uuid": str(charge.event_uuid)}
    assert delete(case, row).status_code == 404
    assert releases(case).count() == 1 and usage(case) == 900


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("mode", ["self-host", "unlimited", "add-false"])
def test_no_actual_finite_debit_creates_no_proof_or_refund(kind, mode, monkeypatch, settings):
    case = lab(monkeypatch, settings, kind)
    cap(case, 1000000, used=900)
    if mode == "self-host":
        settings.PLATFORM_DOMAIN_SUFFIX = ""
    elif mode == "unlimited":
        case.home.resource_limit_overrides = {"storage": None}
        case.home.save(update_fields=["resource_limit_overrides"])
        assert limits.resource_limit(case.home, "storage") is None
    else:
        monkeypatch.setattr(limits, "add_storage", lambda *a, **kw: False)
    row, event, _ = upload(case)
    assert not event.meta
    assert usage(case) == 900
    assert delete(case, row).status_code == 204
    assert not case.store.versions.get(row.object_key)
    assert usage(case) == 900 and not releases(case).exists()


@pytest.mark.parametrize("kind", KINDS)
def test_losing_accounting_context_after_real_charge_never_invents_credit(kind, monkeypatch, settings):
    case = lab(monkeypatch, settings, kind)
    row, _, body = upload(case)
    from tests.document_quota.helpers import clear_identity
    clear_identity()
    assert delete(case, row).status_code == 204
    assert not case.store.versions.get(row.object_key)
    assert usage(case) == len(body) and not releases(case).exists()
    assert not DeploymentDatabaseIdentity.objects.exists()


@pytest.mark.parametrize("kind", KINDS)
def test_cross_tenant_delete_cannot_release_local_charge(kind, monkeypatch, settings):
    case = lab(monkeypatch, settings, kind)
    row, _, body = upload(case)
    from tests.document_safety.helpers import jwt_client, member
    foreign = jwt_client(member(case.other))
    state, calls = snapshot(case), list(case.store.calls)
    response = foreign.delete(reverse(f"{case.prefix}-detail", kwargs={"pk": row.pk}))
    assert response.status_code in (403, 404)
    assert snapshot(case) == state and case.store.calls == calls
    assert usage(case) == len(body) and not releases(case).exists()
