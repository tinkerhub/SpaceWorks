"""Unsupported stored authority refuses before even listing provider bytes."""

from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError

from apps.makerspaces.models import PurgeReceipt
from apps.makerspaces.purge_receipts import retry_cleanup
from tests.makerspaces.purge_test_support import actor, purge_store, receipt

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("field,value", [
    ("source_makerspace_id", 2147483648),
    ("schema_version", 2),
    ("storage_origins", {"private": "unknown", "public_image": "unknown"}),
    ("namespace_prefixes", [["private", "evidence/1/"]]),
    ("namespace_prefixes", [["private", "evidence/"]]),
    ("exact_keys", [["private", "global/key"]]),
    ("exact_keys", [["private", "evidence/2147000001/../foreign"]]),
], ids=["huge-source-id", "unknown-schema", "unproven-origin", "wrong-tenant", "global-prefix", "global-key", "traversal"])
def test_invalid_restored_receipt_authority_is_never_executed(field, value, purge_store):
    user, valid = actor(), receipt()
    values = PurgeReceipt.objects.values().get(pk=valid.pk)
    values.update(id=uuid4(), **{field: value})
    # Model validation cannot be assumed for raw/old-schema restored rows. Insert
    # as a bulk row, then exercise the real service's independent boundary check.
    corrupt = PurgeReceipt(**values)
    PurgeReceipt.objects.bulk_create([corrupt])
    with pytest.raises(ValidationError):
        retry_cleanup(corrupt.pk, user)
    assert not purge_store.calls and not purge_store.deletes
    corrupt.refresh_from_db()
    assert corrupt.last_verified_at is None
