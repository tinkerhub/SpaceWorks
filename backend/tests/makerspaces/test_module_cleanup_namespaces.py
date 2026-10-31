"""Every supported positive grammar removes historical rowless versions only."""
from copy import deepcopy

import pytest
from django.core.exceptions import ValidationError

from apps.makerspaces.models import ModulePurgeReceipt
from apps.makerspaces.module_purge import purge_module
from apps.makerspaces.module_purge_namespaces import clauses, owns_key, validate_clauses
from apps.makerspaces.module_purge_receipt_authority import validate_receipt
from apps.makerspaces.module_purge_receipts import retry_cleanup
from apps.makerspaces.purge_storage import bucket_name
from tests.makerspaces.module_cleanup_support import (
    H, U, actor, delete_historical_context, module_receipt, module_space, module_store, seed_versions,
)

CASES = [
    ("events", "public_image", "event/{m}/" + H + ".png"),
    ("events", "public_image", "event-series/{m}/" + H + ".webp"),
    ("events", "private", "event-certificates/{m}/" + U + ".pdf"),
    ("membership", "public_image", "member/{m}/" + H + ".jpeg"),
    ("bookings", "public_image", "spaces/{m}/{context}/images/" + H + ".jpg"),
    ("maintenance", "private", "machines/{m}/987654321/logs/" + H + ".gcode"),
    ("procurement", "private", "procurement/{m}/987654321/receipts/" + H + ".pdf"),
    ("machine_service", "private", "machine/{m}/987654321/service/" + H),
    ("machine_service", "private", "machine/{m}/queue-987654321/service/" + H),
]


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("module,kind,pattern", CASES)
def test_supported_modules_delete_final_staging_historical_and_manual_late_versions(module, kind, pattern, module_store):
    space = module_space(pk=1)
    other = module_space("module-eleven", pk=11)
    context_id = delete_historical_context(space, module, pattern)
    key = pattern.format(m=space.pk, context=context_id)
    doomed = seed_versions(module_store, kind, key)
    survivors = set()
    for other_kind, other_key in [
        (kind, pattern.format(m=other.pk, context=context_id)), ("public_image", f"items/{space.pk}/{H}.png"),
        ("private", f"evidence/{space.pk}/{H}"), ("private", f"machines/{space.pk}/9/documents/{H}.pdf"),
        ("private", f"machine/{space.pk}/9/documents/{H}.pdf"), ("private", "global/retained.pdf"),
    ]:
        survivors |= seed_versions(module_store, other_kind, other_key)
    # The presign context was deleted above; current-row enumeration cannot find it.
    user = actor()
    receipt, counts = purge_module(space, module, user)
    assert counts == {} and receipt.graph_purged_at and receipt.last_verified_at
    assert not (doomed & module_store.objects.keys())
    assert survivors <= module_store.objects.keys()
    verified = receipt.last_verified_at
    late = module_store.put(bucket_name(kind), f"staging/{key}", b"admitted presign arrived late")
    receipt.refresh_from_db()
    assert receipt.last_verified_at == verified and late in module_store.objects
    assert ModulePurgeReceipt.objects.filter(pk=receipt.pk).exists()
    retry_cleanup(receipt.pk, user)
    assert late not in module_store.objects and survivors <= module_store.objects.keys()
    space.refresh_from_db()
    assert space.storage_bytes_used == 0  # rowless uploads grant no invented credit


@pytest.mark.parametrize("module,kind,key", [
    ("events", "public_image", f"event/1/{H.upper()}.png"),
    ("events", "private", f"event-certificates/1/{U.upper()}.pdf"),
    ("membership", "public_image", f"member/1/{H}.svg"),
    ("bookings", "public_image", f"spaces/1/01/images/{H}.png"),
    ("bookings", "public_image", f"spaces/1/0/images/{H}.png"),
    ("maintenance", "private", f"machines/1/9223372036854775808/logs/{H}.pdf"),
    ("procurement", "private", f"procurement/1/3/receipts/{H}.exe"),
    ("machine_service", "private", f"machine/1/queue-01/service/{H}"),
    ("events", "public_image", f"staging/staging/event/1/{H}.png"),
])
def test_positive_grammar_rejects_noncanonical_types_and_nested_staging(module, kind, key):
    assert not owns_key(clauses(module, 1), kind, key)


@pytest.mark.parametrize("change", ["version-bool", "maker-bool", "version", "vocabulary", "extra"])
def test_frozen_grammar_requires_exact_types_vocabulary_and_fields(change):
    value = deepcopy(clauses("events", 1))
    if change == "version-bool":
        value["version"] = True
    elif change == "maker-bool":
        value["maker"] = True
    elif change == "version":
        value["version"] = 2
    elif change == "extra":
        value["roots"] = ["*"]
    else:
        value["vocabulary"]["images"].append("svg")
    with pytest.raises(ValidationError):
        validate_clauses(value, "events", 1)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("module,kind,key", [
    ("events", "public_image", "event/{m}/bad.png"),
    ("maintenance", "private", "machines/{m}/01/logs/bad.pdf"),
    ("machine_service", "private", "machine/{m}/queue-0/service/bad"),
])
def test_malformed_owned_branch_refuses_before_any_deletion_or_intent(module, kind, key, module_store):
    space = module_space()
    identity = module_store.put(bucket_name(kind), key.format(m=space.pk))
    with pytest.raises(ValidationError, match="Malformed"):
        purge_module(space, module, actor())
    assert identity in module_store.objects and not module_store.deletes
    assert not ModulePurgeReceipt.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("field,value", [
    ("source_makerspace_id", True), ("source_makerspace_id", 2147483648),
    ("schema_version", True), ("schema_version", 2),
    ("exact_keys", [["private", "staging/staging/event-certificates/1/" + U + ".pdf"]]),
    ("exact_keys", [["private", "../global"]]),
    ("charge_obligations", [["certificate:1", "private", "key", True]]),
])
def test_invalid_authority_refuses_before_provider_or_lock(field, value, module_store):
    row = module_receipt(module_space(), completed=True)
    setattr(row, field, value)
    with pytest.raises(ValidationError):
        validate_receipt(row)
    assert module_store.calls == []


@pytest.mark.django_db
@pytest.mark.parametrize("defect", ["version-true", "maker-true", "nested-staging"])
def test_raw_restored_malformed_receipt_refuses_real_retry_before_any_io(defect, module_store):
    from uuid import uuid4
    from django.utils import timezone

    space = module_space(pk=1)
    valid = module_receipt(space, completed=True)
    values = ModulePurgeReceipt.objects.values().get(pk=valid.pk)
    valid.invalidated_at, valid.invalidation_reason = timezone.now(), "recovery"
    valid.save(update_fields=["invalidated_at", "invalidation_reason"])
    values["id"] = uuid4()
    if defect == "version-true":
        values["namespace_clauses"]["version"] = True
    elif defect == "maker-true":
        values["namespace_clauses"]["maker"] = True
    else:
        values["exact_keys"] = [["public_image", f"staging/staging/event/1/{H}.png"]]
    # Restored/raw rows cannot rely on Model.save validation for admission.
    row = ModulePurgeReceipt(**values)
    ModulePurgeReceipt.objects.bulk_create([row])
    with pytest.raises(ValidationError):
        retry_cleanup(row.pk, actor())
    assert module_store.calls == []


@pytest.mark.parametrize("extension", ["pdf", "jpg", "jpeg", "png", "webp", "stl", "3mf", "step", "stp", "obj", "amf", "ply", "gcode", "gco", "iges", "igs", "dxf"])
def test_frozen_maintenance_extensions_and_maximum_canonical_context_are_supported(extension):
    value = clauses("maintenance", 1)
    key = f"machines/1/9223372036854775807/logs/{H}.{extension}"
    assert owns_key(value, "private", key)
    assert owns_key(value, "private", f"staging/{key}")
    assert not owns_key(value, "public_image", key)
    assert not owns_key(value, "private", key.replace("/1/", "/11/", 1))
