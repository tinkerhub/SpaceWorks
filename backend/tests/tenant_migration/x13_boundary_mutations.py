"""Corruptions applied only inside rollback transactions on real builder DBs."""

from django.apps import apps
from django.db import connections
from django.utils import timezone

from apps.tenant_migration.tenant_dump_cross_tenant_verify import verify_lost_edge_manifest
from apps.tenant_migration.tenant_dump_projection_rows import complete_projected_rows, portable_content_rows
from apps.tenant_migration.tenant_dump_raw import projected_raw_digest
from .x13_source_helpers import (
    OWNER, FULL, STUB, CUSTOM, MACHINE, CATEGORY, PRODUCT, REPLACE_CATEGORY,
    BOX, TRANSFER, FILE, QR, put,
)


def update(using, label, pk, **values):
    """Explicit SQL also reaches raw fields and bypasses unrelated workflow guards."""
    model = apps.get_model(label)
    connection = connections[using]
    quote = connection.ops.quote_name
    fields = [model._meta.get_field(name) for name in values]
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {quote(model._meta.db_table)} SET "
            + ", ".join(f"{quote(field.column)} = %s" for field in fields)
            + f" WHERE {quote(model._meta.pk.column)} = %s",
            [field.get_db_prep_save(value, connection)
             for field, value in zip(fields, values.values(), strict=True)] + [pk],
        )
        assert cursor.rowcount == 1


def extra_category(using):
    put(using, "inventory.Category", makerspace_id=OWNER, name="Extra", slug="extra")


def extra_product(using):
    put(using, "inventory.InventoryProduct", makerspace_id=OWNER, category_id=CATEGORY,
        name="Extra", total_quantity=1, available_quantity=1)


def extra_user(using):
    put(using, "accounts.User", username="unreferenced-extra", password="!")


def zero_table(using):
    put(using, "inventory.InventoryAsset", makerspace_id=OWNER, product_id=PRODUCT, asset_tag="extra")


def foreign_graph(using):
    put(using, "makerspaces.Makerspace", id=71001, name="Foreign root", slug="extra-foreign")
    put(using, "inventory.Category", id=71002, makerspace_id=71001, name="Foreign", slug="foreign")
    put(using, "inventory.InventoryProduct", id=71003, makerspace_id=71001,
        category_id=71002, name="Foreign closed graph", total_quantity=1, available_quantity=1)


def replace_identity(using):
    # This category is deliberately unreferenced: closure and counts still pass.
    update(using, "inventory.Category", REPLACE_CATEGORY, id=71004)


def bootstrap_extra(using):
    put(using, "contenttypes.ContentType", app_label="x13", model="contamination")


def bootstrap_content(using):
    model = apps.get_model("auth.Permission")
    pk = model._base_manager.using(using).order_by("pk").values_list("pk", flat=True).first()
    assert pk is not None
    update(using, "auth.Permission", pk, name="Changed permission content")


def builtin_extra(using):
    put(using, "machines.MachineType", name="Unreviewed builtin", slug="unreviewed",
        makerspace_id=None, is_builtin=True)


def builtin_content(using):
    model = apps.get_model("machines.MachineType")
    pk = model._base_manager.using(using).filter(makerspace_id=None).order_by("pk").first().pk
    update(using, "machines.MachineType", pk, name="Changed builtin")


def role_content(using):
    role = apps.get_model("makerspaces.MakerspaceRole")._base_manager.using(using).get(slug="member")
    update(using, "makerspaces.MakerspaceRole", role.pk, granted_actions=["manage_machines"])


def role_extra(using):
    put(using, "makerspaces.MakerspaceRole", makerspace_id=OWNER, name="Injected",
        slug="injected", granted_actions=[], is_default=False, is_protected=False)


def scope_extra(using):
    role = apps.get_model("makerspaces.MakerspaceRole")._base_manager.using(using).get(slug="member")
    put(using, "machines.RoleMachineTypeScope", role_id=role.pk, machine_type_id=CUSTOM)


def scope_content(using):
    scope = apps.get_model("machines.RoleMachineTypeScope")._base_manager.using(using).first()
    update(using, "machines.RoleMachineTypeScope", scope.pk, machine_type_id=CUSTOM)


def fence_actor(using):
    fence = apps.get_model("encryption.PiiMakerspaceWriteFence")._base_manager.using(using).get(makerspace_id=OWNER)
    update(using, "encryption.PiiMakerspaceWriteFence", fence.pk, actor_id=FULL)


def global_fence_actor(using):
    update(using, "encryption.PiiGlobalWriteFence", 1, actor_id=FULL)


def local_pair_cleared(using):
    update(using, "operations.StockTransfer", TRANSFER, source_makerspace_id=None, source_container_id=None)


def foreign_pair_incomplete(using):
    # No foreign FK or dangling row: the *exact* frozen pair is still violated.
    update(using, "operations.StockTransfer", TRANSFER, destination_makerspace_id=OWNER)


def raw_owner(using):
    update(using, "machines.ServiceRequestFile", FILE, owner_user_id=STUB)


def semantic_json(using):
    update(using, "machines.Machine", MACHINE, type_payload={"user_id": 456, "text": "keep"})


def semantic_polymorphic(using):
    update(using, "boxes.QrCode", QR, target_id=REPLACE_CATEGORY)


def ordinary_content(using):
    update(using, "inventory.InventoryProduct", PRODUCT, name="Changed ordinary content")


def mapped_content(using):
    model = apps.get_model("events.EventRegistration")
    pk = model._base_manager.using(using).values_list("pk", flat=True).get()
    update(using, "events.EventRegistration", pk, name="Changed mapped name")


def dropped_session(using):
    put(using, "sessions.Session", session_key="x13-extra", session_data="unused", expire_date=timezone.now())


def runtime_cache(using):
    with connections[using].cursor() as cursor:
        cursor.execute("INSERT INTO spaceworks_cache (cache_key, value, expires) "
                       "VALUES ('x13-extra', 'unused', CURRENT_TIMESTAMP + INTERVAL '1 day')")


def dangling_fk(using):
    update(using, "inventory.InventoryProduct", PRODUCT, category_id=79999)


def sequence_frontier(using):
    with connections[using].cursor() as cursor:
        cursor.execute("SELECT setval(pg_get_serial_sequence('inventory_category', 'id'), 999999, true)")


# Recomputing the old digest is deliberate for semantic/closure/pair cases. It
# demonstrates that their independent source expectations consume actual values.
ROW_CASES = (
    ("extra_category", extra_category, "identity universe", False),
    ("extra_product", extra_product, "identity universe", False),
    ("unreferenced_user", extra_user, "identity universe", False),
    ("zero_expected_table", zero_table, "identity universe", False),
    ("foreign_closed_graph", foreign_graph, "identity universe", False),
    ("equal_count_replacement", replace_identity, "identity universe", False),
    ("bootstrap_extra", bootstrap_extra, "bootstrap", False),
    ("bootstrap_content", bootstrap_content, "bootstrap", False),
    ("builtin_extra", builtin_extra, "identity universe", False),
    ("builtin_content", builtin_content, "bootstrap", False),
    ("role_extra", role_extra, "bootstrap", False),
    ("role_content", role_content, "bootstrap", False),
    ("scope_extra", scope_extra, "bootstrap", False),
    ("scope_content", scope_content, "bootstrap", False),
    ("fence_actor", fence_actor, "bootstrap", False),
    ("global_fence_actor", global_fence_actor, "bootstrap", False),
    ("foreign_pair_incomplete", foreign_pair_incomplete, "frozen source decision", True),
    ("local_pair_unwanted_clear", local_pair_cleared, "frozen source decision", True),
    ("raw_owner", raw_owner, "user closure digest", True),
    ("semantic_json", semantic_json, "Semantic location", True),
    ("semantic_polymorphic", semantic_polymorphic, "Semantic location", True),
    ("ordinary_content", ordinary_content, "sanitized row", False),
    ("mapped_raw", mapped_content, "Mapped raw values", False),
    ("dropped_emptiness", dropped_session, "requires.*empty", False),
    ("runtime_cache", runtime_cache, "requires.*empty", False),
    ("fk_closure", dangling_fk, "Dangling FK closure", False),
    ("sequence_frontier", sequence_frontier, "sequence state", False),
)


def recompute_old_digest(using, kwargs):
    rows = complete_projected_rows(using, kwargs["projected_identities"], kwargs["expected_row_counts"])
    kwargs["expected_projected_digest"] = projected_raw_digest(portable_content_rows(rows))


def corrupt_loss(ledger, mode):
    result = [dict(item) for item in ledger]
    if mode == "omit":
        result.pop()
    elif mode == "add":
        result.append(dict(result[0], source_row_pk=799999))
    else:
        # A different *allowed* reason/field for the same transfer is still a lie
        # about the source; syntax-only validation cannot detect it.
        row = next(item for item in result if item["model_label"] == "operations.StockTransfer"
                   and item["field_name"] == "destination_container")
        row.update(field_name="makerspace", reason_code="foreign_owned_transfer_dropped")
    result.sort(key=lambda item: tuple(str(item[key]) for key in (
        "model_label", "source_row_pk", "field_name", "reason_code")))
    assert verify_lost_edge_manifest(result)
    return result
