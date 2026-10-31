"""Admission must precede provider I/O; retain source/recovery guard policies."""
from datetime import timedelta
from uuid import uuid4

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.backup.models import DeploymentRecoveryState
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from apps.tenant_migration.models import SourceMigrationGate
from tests.document_safety.helpers import (
    accepted_body, finalize, jwt_client, lab, member, payload, presign, snapshot,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("kind", ["receipt", "asset", "machine"])
@pytest.mark.parametrize("operation", ["presign", "finalize"])
@pytest.mark.parametrize("denial", ["foreign", "role", "origin", "module"])
def test_real_staff_guard_denial_has_no_provider_calls_or_mutations(
    kind, operation, denial, monkeypatch, settings,
):
    case = lab(monkeypatch, settings, kind)
    key, _ = presign(case)
    case.store.seed(case.module.staging_key(key), accepted_body("application/pdf"))
    headers = {}
    if denial == "foreign":
        case.client = jwt_client(member(case.other))
    elif denial == "role":
        case.client = jwt_client(member(case.home, "member"))
    elif denial == "origin":
        # Give the same authenticated actor both tenants: only origin scoping denies.
        member(case.other)  # Provision its protected roles through the normal helper.
        role = MakerspaceRole.objects.get(makerspace=case.other, slug="space_manager")
        MakerspaceMembership.objects.create(
            makerspace=case.other, user=case.actor, role="space_manager", assigned_role=role,
        )
        headers = {"HTTP_ORIGIN": f"https://{case.other.frontend_domain}"}
    else:
        case.home.enabled_modules = [k for k in case.home.enabled_modules if k != case.module_key]
        case.home.save(update_fields=["enabled_modules"])
    before, calls = snapshot(case), list(case.store.calls)
    if operation == "presign":
        response = case.client.post(
            reverse(f"{case.prefix}-presign", kwargs={"pk": case.target.pk}),
            {"filename": "bill.pdf", "content_type": "application/pdf"}, format="json", **headers,
        )
    else:
        response = finalize(case, key, **headers)
    if denial == "module":
        assert response.status_code == 400 and "module" in response.data
    elif denial == "origin":
        assert response.status_code == 403
    elif denial == "foreign":
        assert response.status_code == 404
    else:
        assert response.status_code == (404 if kind == "receipt" else 403)
    assert snapshot(case) == before and case.store.calls == calls


@pytest.mark.parametrize("kind", ["receipt", "asset", "machine"])
@pytest.mark.parametrize("bad_key", ["foreign", "other-resource", "legacy-flat"])
def test_bad_object_binding_is_refused_before_transport(kind, bad_key, monkeypatch, settings):
    case = lab(monkeypatch, settings, kind)
    key, _ = presign(case)
    parts = key.split("/")
    if bad_key == "foreign":
        parts[1] = str(case.other.pk)
    elif bad_key == "other-resource":
        parts[2] = str(case.target.pk + 100000)
    else:
        parts = [parts[0], parts[1], "legacy.pdf"]
    before, calls = snapshot(case), list(case.store.calls)
    response = finalize(case, "/".join(parts))
    assert response.status_code == 400
    assert snapshot(case) == before and case.store.calls == calls


@pytest.mark.parametrize("kind", ["receipt", "asset", "machine"])
@pytest.mark.parametrize("mime", ["application/pdf", "image/png"])
def test_real_validation_rejects_invalid_bytes_without_publication_or_debit(kind, mime, monkeypatch, settings):
    case = lab(monkeypatch, settings, kind)
    key, _ = presign(case, mime)
    case.store.seed(case.module.staging_key(key), b"<html>not a document</html>", mime)
    before = snapshot(case)
    response = finalize(case, key)
    assert response.status_code == 400
    assert snapshot(case) == before
    assert key not in case.store.objects and not case.store.put_bodies
    assert all(stream.closed for stream in case.store.streams)


@pytest.mark.parametrize("kind", ["receipt", "asset", "machine"])
@pytest.mark.parametrize("policy", ["source-quiesced", "source-draining", "recovery-quiesced"])
def test_source_and_recovery_refusal_do_not_enter_provider_or_change_state(kind, policy, monkeypatch, settings):
    case = lab(monkeypatch, settings, kind)
    key, _ = presign(case)
    case.store.seed(case.module.staging_key(key), accepted_body("application/pdf"))
    if policy.startswith("source"):
        now = timezone.now()
        SourceMigrationGate.objects.create(
            makerspace=case.home, state=policy.removeprefix("source-"), owner_id=uuid4(),
            heartbeat_at=now, lease_expires_at=now + timedelta(minutes=10), actor=case.actor,
        )
    else:
        state = DeploymentRecoveryState.load()
        state.mode = DeploymentRecoveryState.Mode.QUIESCED
        state.save(update_fields=["mode", "updated_at"])
    before, calls = snapshot(case), list(case.store.calls)
    response = case.client.post(case.url, payload(key), format="json")
    assert response.status_code == (423 if policy.startswith("source") else 503), response.data
    assert snapshot(case) == before and case.store.calls == calls
