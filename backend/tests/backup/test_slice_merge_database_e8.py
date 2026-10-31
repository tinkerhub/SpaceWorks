import uuid

import pytest
from django.db import DatabaseError, connection, transaction

from apps.backup.models import B1RestoreComponentState, B1RestoreOperationState
from apps.backup.slice_merge_database import (
    MERGE_ROLE,
    merge_schema_name,
    protect_target_tables,
    provision_merge_role,
)
from apps.inventory.models import Category
from apps.makerspaces.models import Makerspace
from tests.backup.x07_installation_test_helpers import (
    fence, finish_installation, operation, prepared,
)


pytestmark = pytest.mark.django_db(transaction=True)


def _merging_component():
    case = prepared([("broad_fence", fence(
        [uuid.uuid4()], table="inventory_inventoryproduct",
    ))], makerspace_id=800008)
    finish_installation(case)
    current_operation = operation(case)
    component = B1RestoreComponentState.objects.get(operation_id=current_operation.pk)
    B1RestoreComponentState.objects.filter(pk=component.pk).update(state="merging")
    component.refresh_from_db()
    return current_operation, component


def _stage_context(operation, component, category):
    schema = merge_schema_name(operation.operation_id, [component.component_id])
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE SCHEMA "{schema}"')
        cursor.execute(
            f'CREATE TABLE "{schema}".backup_b1_context '
            '(operation_id uuid NOT NULL, component_id uuid PRIMARY KEY)'
        )
        cursor.execute(
            f'INSERT INTO "{schema}".backup_b1_context VALUES (%s, %s)',
            [operation.operation_id, component.component_id],
        )
        cursor.execute(
            f'CREATE TABLE "{schema}".backup_b1_deltas ('
            'component_id uuid, table_name text, row_pk jsonb, column_name text, '
            'old_value jsonb, new_value jsonb)'
        )
        cursor.execute(
            f'CREATE TABLE "{schema}".inventory_category '
            '(LIKE public.inventory_category INCLUDING GENERATED)'
        )
        cursor.execute(
            f'ALTER TABLE "{schema}".inventory_category '
            'ADD COLUMN __b1_component_id uuid NOT NULL'
        )
        cursor.execute(
            f'INSERT INTO "{schema}".inventory_category '
            '(id, makerspace_id, name, slug, display_order, icon, code, code_sequence, '
            'created_at, updated_at, __b1_component_id) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
            [category.pk, category.makerspace_id, "occupied replacement", category.slug,
             category.display_order, category.icon, category.code, category.code_sequence,
             category.created_at, category.updated_at, component.component_id],
        )
    provision_merge_role()
    protect_target_tables(schema, {"inventory_category"})
    return schema


def _set_role(cursor, operation, component, schema):
    cursor.execute(f"SET LOCAL ROLE {MERGE_ROLE}")
    cursor.execute("SELECT set_config('app.b1_merge_operation', %s, true)", [str(operation.operation_id)])
    cursor.execute("SELECT set_config('app.b1_merge_component', %s, true)", [str(component.component_id)])
    cursor.execute("SELECT set_config('app.b1_merge_schema', %s, true)", [schema])


def test_merge_role_cannot_overwrite_update_or_setval():
    operation, component = _merging_component()
    space = Makerspace.objects.create(name="E8 role target", slug="e8-role-target")
    category = Category.objects.create(makerspace=space, name="occupied", slug="occupied")
    schema = _stage_context(operation, component, category)
    try:
        with pytest.raises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                _set_role(cursor, operation, component, schema)
                cursor.execute(
                    "INSERT INTO inventory_category "
                    "(id, makerspace_id, name, slug, display_order, icon, created_at, updated_at) "
                    f"SELECT id, makerspace_id, name, slug, display_order, icon, created_at, updated_at "
                    f'FROM "{schema}".inventory_category'
                )
        with pytest.raises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                _set_role(cursor, operation, component, schema)
                cursor.execute("UPDATE inventory_category SET name = 'outside delta' WHERE id = %s", [category.pk])
        with pytest.raises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                _set_role(cursor, operation, component, schema)
                cursor.execute("SELECT setval(pg_get_serial_sequence('inventory_category', 'id'), 999999)")
    finally:
        with connection.cursor() as cursor:
            cursor.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
