from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.test import override_settings

from apps.checkin.identity import resolve_principal
from apps.checkin.models import CheckinIdentity
from apps.encryption.blind_index import search_key_fingerprint, sync_checkin_hash
from apps.encryption.crypto import PiiAuthenticationFailed, decrypt_with_key_loader
from apps.encryption.models import SearchKeyGeneration
from apps.encryption.registry import ALL_FIELDS, SECONDARY_FIELDS, SOURCE_FIELDS
from apps.encryption.services import get_dek
from apps.hardware_requests.models import HardwareRequest
from apps.makerspaces.models import Makerspace


pytestmark = pytest.mark.django_db


@pytest.fixture
def space():
    return Makerspace.objects.create(name="Mapper Space", slug="mapper-space")


@pytest.fixture
def requester():
    return get_user_model().objects.create_user(username="mapper-requester")


@pytest.fixture
def enabled():
    from tests.encryption.conftest import enabled_encryption

    with enabled_encryption():
        yield


def make_request(space, requester):
    return HardwareRequest.objects.create(
        makerspace=space, requester=requester, requester_username="mapper-requester",
        requester_name="Ada Lovelace", requester_contact_email="ada@example.test",
        requester_contact_phone="+91 9999900000", requested_for="oscilloscope",
    )


def test_registry_matches_the_post_b7c_source_and_secondary_allowlists():
    # 18 at B7c, plus the two post-event source fields (EventFeedbackResponse.answers_snapshot
    # and EventAttendanceCertificate.recipient_name), plus the two the check-in gate added
    # (HardwareRequest.checkin_project_name and CheckinIdentity.mid).
    # The counts are asserted so that encrypting a new column is a visible decision here.
    assert len(SOURCE_FIELDS) == 22
    assert len(SECONDARY_FIELDS) == 4
    assert len(ALL_FIELDS) == 26
    assert {item.model_label for item in SECONDARY_FIELDS} == {"integrations.EmailLog"}


def test_flag_off_is_byte_for_byte_plaintext(space, requester):
    request = make_request(space, requester)
    with connection.cursor() as cursor:
        cursor.execute("SELECT requester_name FROM hardware_requests_hardwarerequest WHERE id = %s", [request.pk])
        assert cursor.fetchone()[0] == "Ada Lovelace"


def test_enabled_save_encrypts_and_round_trips_with_row_bound_aad(enabled, space, requester):
    request = make_request(space, requester)
    with connection.cursor() as cursor:
        cursor.execute("SELECT requester_name FROM hardware_requests_hardwarerequest WHERE id = %s", [request.pk])
        raw = cursor.fetchone()[0]
    assert raw.startswith("pii:gcm:v1:")
    assert request.requester_name == "Ada Lovelace"
    loaded = HardwareRequest.objects.get(pk=request.pk)
    assert loaded.requester_name == "Ada Lovelace"
    with pytest.raises(PiiAuthenticationFailed):
        decrypt_with_key_loader(raw, makerspace_id=space.pk, table=loaded._meta.db_table, pk=loaded.pk + 1, field="requester_name", load_dek=lambda version: get_dek(space.pk, version))


def test_enabled_mapped_bulk_writes_are_rejected(enabled, space, requester):
    request = make_request(space, requester)
    with pytest.raises(RuntimeError):
        HardwareRequest.objects.filter(pk=request.pk).update(requester_name="other")
    with pytest.raises(RuntimeError):
        HardwareRequest.objects.bulk_update([request], ["requester_name"])


def test_checkin_hash_sync_is_noop_when_encryption_is_disabled(space, requester):
    identity = CheckinIdentity(makerspace=space, user=requester, mid="443")

    with override_settings(PII_ENCRYPTION_ENABLED=False):
        sync_checkin_hash(identity, identity.mid)

    assert identity.mid_exact_hash is None
    assert identity.mid_hash_generation is None


def test_checkin_save_rehashes_after_rotation_and_resolver_reuses_principal(
    enabled,
    space,
):
    entry = SimpleNamespace(mid=443, name="Ada Example")
    identity = resolve_principal(space, entry)
    original_hash = bytes(identity.mid_exact_hash)
    original_user_id = identity.user_id
    old_generation = identity.mid_hash_generation

    new_secret = Fernet.generate_key().decode()
    with override_settings(PII_SEARCH_HASH_KEY=new_secret):
        new_generation = SearchKeyGeneration.objects.create(
            generation=old_generation.generation + 1,
            key_fingerprint=search_key_fingerprint(),
            status=SearchKeyGeneration.Status.BUILDING,
        )
        with transaction.atomic():
            old_generation.status = SearchKeyGeneration.Status.RETIRED
            old_generation.save(update_fields=["status"])
            new_generation.status = SearchKeyGeneration.Status.ACTIVE
            new_generation.save(update_fields=["status"])

        identity.save(update_fields=["mid"])
        identity.refresh_from_db()

        assert identity.mid_hash_generation == new_generation
        assert bytes(identity.mid_exact_hash) != original_hash

        resolved = resolve_principal(space, entry)
        assert resolved.pk == identity.pk
        assert resolved.user_id == original_user_id
        assert CheckinIdentity.objects.filter(makerspace=space).count() == 1
