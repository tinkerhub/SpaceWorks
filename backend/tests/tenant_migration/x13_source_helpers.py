"""Real migrated source graph; no catalog overrides or target-derived expectations."""

from datetime import date, time, timedelta
from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

from django.apps import apps
import pytest
from django.db import connections, transaction
from django.utils import timezone

from apps.tenant_migration.tenant_dump_catalog import CATALOG_SCHEMA_SHA256
from apps.backup.digests import sha256_file
from apps.tenant_migration.tenant_dump_database import dump_scratch_database, migrated_scratch_database
from apps.tenant_migration.tenant_dump_projection_expectations import capture_projection_expectations
from apps.tenant_migration.tenant_dump_projection_proof import FORMAT, canonical_digest
from apps.tenant_migration.tenant_dump_source_projection import project_makerspace_source
from apps.tenant_migration.tenant_dump_errors import TenantDumpVerificationError

OWNER, FOREIGN, FULL, STUB = 41001, 41002, 42001, 42002
CUSTOM, MACHINE, BUILTIN_MACHINE = 910001, 43001, 43002
CATEGORY, PRODUCT, REPLACE_CATEGORY = 44001, 44002, 44003
BOX, FOREIGN_BOX, TRANSFER, FOREIGN_TRANSFER = 45001, 45002, 46001, 46002
LOCAL_LINE, FOREIGN_LINE = 46003, 46004
FILE, QR, AUDIT, MEMBERSHIP = 47001, 48001, 49001, 50001
SNAPSHOT = dict(actor_username="deleted-source-actor", actor_display="Historical actor",
                source_user_id="1", recorded_at="2026-01-01T00:00:00Z")


def put(using, model_label, **values):
    """Bulk insert bypasses application side effects, retaining real DB constraints."""
    model = apps.get_model(model_label)
    row = model(**values)
    model._base_manager.using(using).bulk_create([row])
    return row


def seed_source(using):
    put(using, "makerspaces.Makerspace", id=OWNER, name="X13 source", slug="x13-source")
    put(using, "makerspaces.Makerspace", id=FOREIGN, name="Foreign", slug="x13-foreign")
    # Bulk insertion intentionally skips provisioning signals; mapped-row SQL
    # still requires each source tenant's real open PII write fence.
    for makerspace_id in (OWNER, FOREIGN):
        put(using, "encryption.PiiMakerspaceWriteFence", makerspace_id=makerspace_id)
    for pk, username in ((FULL, "ordinary-user"), (STUB, "shared-user")):
        put(using, "accounts.User", id=pk, username=username, password="!",
            email=f"{username}@example.test")
    # Historical actor #1 was deleted. A different current principal now occupies
    # that PK; literal snapshot identity must never resolve to this user's name.
    put(using, "accounts.User", id=1, username="unrelated-reused-pk", password="!")
    put(using, "makerspaces.MakerspaceMembership", id=MEMBERSHIP, makerspace_id=OWNER,
        user_id=FULL, activated_actor_snapshot=SNAPSHOT)
    put(using, "makerspaces.MakerspaceMembership", makerspace_id=OWNER, user_id=STUB)
    put(using, "makerspaces.MakerspaceMembership", makerspace_id=FOREIGN, user_id=STUB)
    put(using, "makerspaces.MakerspaceMembership", makerspace_id=OWNER, user_id=1)

    # Move a source builtin away from its target migration PK. Literal history at
    # its old PK must remain inert when the target's unrelated builtin occupies it.
    Type = apps.get_model("machines.MachineType")
    builtin = Type._base_manager.using(using).order_by("pk").first()
    old_pk = builtin.pk
    Type._base_manager.using(using).filter(pk=old_pk).update(id=900001)
    put(using, "machines.MachineType", id=CUSTOM, makerspace_id=OWNER,
        slug="x13-custom", name="Custom type", capability_config={"source_id": 123})
    put(using, "machines.Machine", id=MACHINE, makerspace_id=OWNER,
        machine_type_id=CUSTOM, name="Custom machine", type_payload={"user_id": 123, "text": "keep"})
    put(using, "machines.Machine", id=BUILTIN_MACHINE, makerspace_id=OWNER,
        machine_type_id=900001, name="Builtin machine")
    put(using, "machines.MachineOperator", machine_id=MACHINE, user_id=FULL, assigned_by_id=STUB)
    put(using, "machines.ServiceRequestFile", id=FILE, makerspace_id=OWNER,
        machine_id=MACHINE, kind="attachment", object_key="x13/file", owner_user_id=FULL)
    put(using, "inventory.Category", id=CATEGORY, makerspace_id=OWNER, name="Tools", slug="tools")
    put(using, "inventory.Category", id=REPLACE_CATEGORY, makerspace_id=OWNER,
        name="Replaceable", slug="replaceable")
    put(using, "inventory.InventoryProduct", id=PRODUCT, makerspace_id=OWNER,
        category_id=CATEGORY, name="Ordinary stock", total_quantity=4, available_quantity=4)
    put(using, "boxes.Box", id=BOX, makerspace_id=OWNER, label="Own", code="x13-own")
    put(using, "boxes.Box", id=FOREIGN_BOX, makerspace_id=FOREIGN, label="Foreign", code="x13-foreign")
    put(using, "boxes.QrCode", id=QR, makerspace_id=OWNER, target_type="product", target_id=PRODUCT)
    put(using, "operations.StockTransfer", id=TRANSFER, makerspace_id=OWNER,
        source_makerspace_id=OWNER, source_container_id=BOX,
        destination_makerspace_id=FOREIGN, destination_container_id=FOREIGN_BOX,
        created_by_id=FULL, reason="Historical outbound")
    put(using, "operations.StockTransferLine", id=LOCAL_LINE, transfer_id=TRANSFER, product_id=PRODUCT, quantity=1)
    put(using, "operations.StockTransfer", id=FOREIGN_TRANSFER, makerspace_id=FOREIGN,
        source_makerspace_id=FOREIGN, source_container_id=FOREIGN_BOX,
        destination_makerspace_id=OWNER, destination_container_id=BOX, reason="Inbound")
    put(using, "operations.StockTransferLine", id=FOREIGN_LINE, transfer_id=FOREIGN_TRANSFER, product_id=PRODUCT)
    seed_collaborators(using)
    put(using, "events.EventRegistration", event_id=51001, member_id=STUB,
        name="Shared person", email="shared@example.test", phone="",
        registered_via_makerspace_id=FOREIGN, payment_via_makerspace_id=FOREIGN)
    put(using, "payments.Payment", makerspace_id=OWNER, member_id=FULL, created_by_id=FULL,
        subject_type="booking", subject_id=123, subject_label="Readable history",
        amount=Decimal("42.75"), currency="inr", status="paid_online", provider="razorpay",
        via_makerspace_id=FOREIGN, external_order_id="order-x13", external_payment_id="pay-x13")
    put(using, "audit.AuditLog", id=AUDIT, makerspace_id=OWNER, actor_id=FULL,
        action="historical", target_type="machines.machinetype", target_id=str(old_pk),
        meta={"actor": SNAPSHOT, "ordinary_user_content": {"user_id": 123}})
    with connections[using].cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    return old_pk


def seed_collaborators(using):
    now = timezone.now()
    for offset, host, invited in ((0, OWNER, FOREIGN), (1, FOREIGN, OWNER), (2, OWNER, OWNER)):
        event = put(using, "events.Event", id=51001 + offset, makerspace_id=host,
                    title=f"Occurrence {offset}", starts_at=now, ends_at=now + timedelta(hours=1))
        series = put(using, "events.EventSeries", id=52001 + offset, makerspace_id=host,
                     title=f"Series {offset}", recurrence_timezone="UTC", dtstart_local_date=date(2026, 1, 1),
                     dtstart_local_time=time(12), recurrence_rule="FREQ=WEEKLY", duration_minutes=60)
        put(using, "events.EventCollaborator", id=53001 + offset,
            event_id=event.pk, makerspace_id=invited)
        put(using, "events.EventSeriesCollaborator", id=54001 + offset,
            series_id=series.pk, makerspace_id=invited)


def freeze_source(database, tmp_path):
    """Close the immutable source alias before the builder receives its inputs."""
    capture_id = str(uuid4())
    with migrated_scratch_database(OWNER, uuid4(), database=database) as (using, name):
        old_builtin_pk = seed_source(using)
        source_dump = tmp_path / "database.source.dump"
        dump_scratch_database(name, source_dump, database=database)
        catalog = CATALOG_SCHEMA_SHA256  # Root owns schema review; never bless runtime drift.
        policy = canonical_digest(dict(format=FORMAT, policy_version=6, catalog_digest=catalog,
                                       source_encryption_mode=False, companion_slice=False))
        bindings = dict(capture_id=capture_id, source_database_image_sha256=sha256_file(source_dump),
                        catalog_sha256=catalog, derivation_policy_sha256=policy, using=using)
        with transaction.atomic(using=using):
            with connections[using].cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            projection = project_makerspace_source(OWNER, using=using, capture_id=capture_id)
            expectations = capture_projection_expectations(projection, **bindings)
            assert_actual_source_losses(expectations)
            for supplied in changed_source_ledgers(projection.cross_tenant_lost_edges):
                with pytest.raises(TenantDumpVerificationError, match="immutable source ownership"):
                    capture_projection_expectations(replace(projection, cross_tenant_lost_edges=tuple(supplied)), **bindings)
    return projection, expectations, old_builtin_pk


def assert_actual_source_losses(expectations):
    # Independently named from seed_source, never copied out of the manifest.
    actual = {(row["model_label"], row["source_row_pk"], row["field_name"], row["reason_code"])
              for row in expectations.expected_cross_tenant_lost_edges}
    expected = set()
    for label, first, parent, reason in (
        ("events.EventCollaborator", 53001, "event", "foreign_collaborator_dropped"),
        ("events.EventSeriesCollaborator", 54001, "series", "foreign_series_collaborator_dropped"),
    ):
        expected.add((label, first, "makerspace", reason))
        expected.add((label, first + 1, parent, reason))
    expected |= {
        ("operations.StockTransfer", TRANSFER, "destination_makerspace", "foreign_counterparty_nulled"),
        ("operations.StockTransfer", TRANSFER, "destination_container", "foreign_counterparty_container_nulled"),
        ("operations.StockTransfer", FOREIGN_TRANSFER, "makerspace", "foreign_owned_transfer_dropped"),
        ("operations.StockTransferLine", FOREIGN_LINE, "transfer", "foreign_owned_transfer_line_dropped"),
    }
    assert actual == expected


def changed_source_ledgers(ledger):
    original = [dict(item) for item in ledger]
    omitted = original[:-1]
    added = [*original, dict(original[0], source_row_pk=799999)]
    changed = [dict(item) for item in original]
    changed[0]["source_row_pk"] += 100000
    key = lambda item: tuple(str(item[name]) for name in (
        "model_label", "source_row_pk", "field_name", "reason_code"))
    return tuple(sorted(rows, key=key) for rows in (omitted, added, changed))
