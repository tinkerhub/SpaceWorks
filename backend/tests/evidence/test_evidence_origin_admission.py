"""EVID-S05: browser origin admission precedes evidence and provider side effects."""
import pytest

from apps.accounts import rbac
from apps.accounts.models import User
from apps.evidence.models import EvidencePhoto
from apps.evidence import storage
from apps.makerspaces.models import Makerspace
from tests.evidence.safety_access_helpers import (
    actor, assert_no_effects, assert_presign, detail_url, jwt_client, origin,
    photo, safety_lab, snapshot, upload, upload_url,
)
from tests.evidence.safety_transport_helpers import native_client, server_client, signed_request
from tests.atomic_publication.store import png


pytestmark = pytest.mark.django_db
DENIED = {"detail": "You do not have permission to perform this action."}


@pytest.fixture
def lab(monkeypatch, settings):
    return safety_lab(monkeypatch, settings)


@pytest.mark.parametrize("with_origin", [True, False], ids=["same-origin", "originless"])
def test_membership_only_inventory_manager_can_upload_and_read(lab, with_origin):
    assert lab.user.role == User.Role.REQUESTER
    assert all(member.assigned_role.slug == "inventory_manager" for member in lab.memberships)
    assert rbac.can(lab.user, rbac.Action.UPLOAD_EVIDENCE, lab.home.pk)
    headers = origin(lab.home) if with_origin else {}
    response = upload(lab, headers=headers)
    assert response.status_code == 201, response.data
    evidence = EvidencePhoto.objects.get(pk=response.data["evidence_id"])
    assert_presign(lab, evidence)
    lab.store.seed(evidence.object_key, png(), "image/png")
    lab.store.calls.clear()

    response = lab.client.get(detail_url(evidence), **headers)

    assert response.status_code == 200, response.data
    assert response.data["url"] == "https://objects.example.test/signed"
    assert [name for name, _ in lab.store.calls] == ["head", "presign"]
    assert lab.store.calls[0][1]["Key"] == evidence.object_key
    assert lab.store.calls[1][1]["operation"] == "get_object"


@pytest.mark.parametrize("endpoint", ["upload", "detail"])
def test_foreign_origin_refused_even_when_actor_has_both_tenants(lab, endpoint):
    evidence = photo(lab, makerspace=lab.other)
    assert rbac.can(lab.user, rbac.Action.UPLOAD_EVIDENCE, lab.other.pk)
    before, calls = snapshot(), list(lab.store.calls)

    response = (upload(lab, lab.other, headers=origin(lab.home)) if endpoint == "upload"
                else lab.client.get(detail_url(evidence), **origin(lab.home)))

    assert response.status_code == 403
    assert response.data == DENIED
    assert_no_effects(lab, before, calls)


@pytest.mark.parametrize("endpoint", ["upload", "detail"])
def test_unresolved_target_from_tenant_origin_keeps_standard_403(lab, endpoint):
    missing = max(lab.home.pk, lab.other.pk) + 100_000
    before, calls = snapshot(), list(lab.store.calls)
    response = (upload(lab, missing, headers=origin(lab.home)) if endpoint == "upload"
                else lab.client.get(detail_url(missing), **origin(lab.home)))
    assert response.status_code == 403
    assert response.data == DENIED
    assert_no_effects(lab, before, calls)


@pytest.mark.parametrize("restriction,status", [("suspended", 403), ("inactive", 401), ("rotation", 403)])
@pytest.mark.parametrize("endpoint", ["upload", "detail"])
def test_active_user_checks_survive_real_staff_jwt(lab, restriction, status, endpoint):
    evidence = photo(lab)
    if restriction == "suspended":
        lab.user.access_status = User.AccessStatus.SUSPENDED
    elif restriction == "inactive":
        lab.user.is_active = False
    else:
        lab.user.must_change_password = True
    lab.user.save()
    before, calls = snapshot(), list(lab.store.calls)

    response = (upload(lab, headers=origin(lab.home)) if endpoint == "upload"
                else lab.client.get(detail_url(evidence), **origin(lab.home)))

    assert response.status_code == status, response.data
    if status == 403:
        assert response.data == DENIED
    else:
        assert response.data == {"detail": "User is inactive", "code": "user_inactive"}
    assert_no_effects(lab, before, calls)


@pytest.mark.parametrize("hidden", [False, True], ids=["no-action-scope", "superadmin-hidden"])
def test_detail_404_after_origin_admission_passes(lab, hidden):
    evidence = photo(lab)
    user = actor("safety-reader")
    if hidden:
        user.role = User.Role.SUPERADMIN
        user.save(update_fields=["role"])
        Makerspace.objects.filter(pk=lab.home.pk).update(superadmin_access_enabled=False)
    client = jwt_client(user)
    before, calls = snapshot(), list(lab.store.calls)

    response = client.get(detail_url(evidence), **origin(lab.home))

    assert response.status_code == 404
    assert response.data == {"detail": "No EvidencePhoto matches the given query."}
    assert_no_effects(lab, before, calls)


def test_originless_native_selected_tenant_preserves_inventory_authority(lab):
    client, grant = native_client(lab)
    headers = {"HTTP_X_MAKERSPACE_ID": str(lab.home.pk)}
    response = upload(lab, client=client, headers=headers)
    assert response.status_code == 201, response.data
    evidence = EvidencePhoto.objects.get(pk=response.data["evidence_id"])
    lab.store.seed(storage.staging_key(evidence.object_key), png(), "image/png")
    assert_presign(lab, evidence)
    lab.store.calls.clear()

    response = client.get(detail_url(evidence), **headers)

    assert response.status_code == 200, response.data
    assert [name for name, _ in lab.store.calls] == ["head", "head", "presign"]
    assert lab.store.calls[-1][1]["Key"] == storage.staging_key(evidence.object_key)
    grant.refresh_from_db()
    assert grant.status == "active"


def test_current_hmac_server_transport_keeps_originless_staff_profile(lab, settings):
    credential = server_client(lab, settings)
    # HMAC is enforced on the real public prefix; evidence uses staff JWT + RBAC.
    # Prove this credential/signature actually authenticates before compatibility calls.
    settings.API_CLIENT_AUTH_REQUIRED = True
    public = f"/api/v1/public/{lab.home.slug}/inventory/"
    response = signed_request(lab.client, credential, "GET", public)
    assert response.status_code == 200, response.data
    assert response.wsgi_request.api_client.pk == credential[0].pk
    settings.API_CLIENT_AUTH_REQUIRED = False

    response = signed_request(lab.client, credential, "POST", upload_url(lab.home), {
        "evidence_type": "issue", "content_type": "image/png",
    })
    assert response.status_code == 201, response.data
    evidence = EvidencePhoto.objects.get(pk=response.data["evidence_id"])
    assert_presign(lab, evidence)
    lab.store.seed(evidence.object_key, png(), "image/png")
    lab.store.calls.clear()
    response = signed_request(lab.client, credential, "GET", detail_url(evidence))
    assert response.status_code == 200, response.data
    assert [name for name, _ in lab.store.calls] == ["head", "presign"]
