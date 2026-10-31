"""Native batch inlines keep historical snapshots without projecting foreign QR state."""
import re
from html import unescape

import pytest
from django.test import Client
from django.urls import reverse
from django.utils.html import escape, strip_tags

from tests.qr_batch_projection_safety.helpers import (
    collect, item_rows, move, read_state, snapshot_fields,
)

pytestmark = pytest.mark.django_db
SNAPSHOT_COLUMNS = ("label_text", "target_type", "target_id", "sort_order")


def native_detail(lab):
    client = Client(HTTP_HOST="testserver")
    client.force_login(lab.global_actor)
    before = read_state()

    response = client.get(reverse("admin:operations_qrprintbatch_change", args=[lab.batch.pk]))

    assert response.status_code == 200
    assert response.context["original"].pk == lab.batch.pk
    assert response.context["original"].makerspace_id == lab.home.pk
    inlines = response.context["inline_admin_formsets"]
    assert len(inlines) == 1
    inline = inlines[0]
    forms = inline.formset.forms
    assert forms
    # ModelForm exclusion matters even when the displayed QR value is readonly.
    assert "qr_code" not in inline.formset.form.base_fields
    assert "qr_code" not in inline.formset.empty_form.fields
    assert all("qr_code" not in form.fields for form in forms)
    html = response.content.decode()
    assert not re.search(
        r'<(?:input|select|textarea)\b[^>]*\bname=["\'][^"\']*-qr_code["\']', html,
    )
    columns = {}
    for name in ("qr_code_display", *SNAPSHOT_COLUMNS):
        columns[name] = re.findall(
            rf'<td\b[^>]*\bclass="[^"]*\bfield-{name}\b[^"]*"[^>]*>(.*?)</td>',
            html, re.S,
        )
        assert len(columns[name]) == len(forms), (name, columns[name])
    rows = [
        {name: values[index] for name, values in columns.items()}
        for index in range(len(forms))
    ]
    # Complete domain/QR/item/audit rows include timestamps and scan history.
    assert read_state() == before
    return forms, rows


@pytest.mark.parametrize("hidden_b", [True, False], ids=["hidden-B", "visible-B"])
def test_foreign_qr_is_unavailable_in_actual_native_batch_inline(lab, hidden_b):
    original = collect(lab, label='Original <label> & "history"', order=20)
    owned = collect(lab, label="Still owned by A", order=10)
    snapshots = item_rows(lab.batch)
    expected = [snapshot_fields(owned.item), snapshot_fields(original.item)]
    destination = move(lab, original, "product")
    assert original.code.target_id == destination.pk
    assert original.code.target_id != original.item.target_id
    # Operator configuration follows the fully authorized canonical move.
    # No workflow/permission/source-gate override is used to create this history.
    if hidden_b:
        lab.other.superadmin_access_enabled = False
        lab.other.save(update_fields=["superadmin_access_enabled"])
    assert lab.other.superadmin_access_enabled is not hidden_b
    assert lab.home.superadmin_access_enabled
    assert lab.global_actor.is_superuser
    assert not lab.global_actor.makerspace_memberships.exists()

    forms, rows = native_detail(lab)

    assert [form.instance.pk for form in forms] == [item["id"] for item in expected]
    for row, snapshot in zip(rows, expected):
        assert {
            name: unescape(strip_tags(row[name])).strip() for name in SNAPSHOT_COLUMNS
        } == {name: str(snapshot[name]) for name in SNAPSHOT_COLUMNS}
    foreign_cell = rows[1]["qr_code_display"]
    assert unescape(strip_tags(foreign_cell)).strip() == "QR unavailable"
    assert "<a" not in foreign_cell
    foreign_url = reverse("admin:boxes_qrcode_change", args=[original.code.pk])
    current_text = f"{original.code.target_type}:{original.code.target_id} [{original.code.status}]"
    for forbidden in (
        foreign_url, current_text, original.code.status, original.code.payload,
        f"{original.code.target_type}:{original.code.target_id}", destination.name,
    ):
        assert forbidden not in foreign_cell
    # Numerical historical IDs remain legitimate in the snapshot cells and FK.
    assert str(original.item.target_id) == unescape(strip_tags(rows[1]["target_id"])).strip()
    assert forms[1].instance.qr_code_id == original.code.pk
    owned_url = reverse("admin:boxes_qrcode_change", args=[owned.code.pk])
    owned_text = f"{owned.code.target_type}:{owned.code.target_id} [{owned.code.status}]"
    assert f'<a href="{owned_url}">{escape(owned_text)}</a>' in rows[0]["qr_code_display"]
    assert item_rows(lab.batch) == snapshots


def test_same_maker_native_inline_renders_escaped_text_and_actual_change_link(lab):
    label = '<img src=x onerror="alert(1)"> & original label'
    original = collect(lab, label=label, order=7)
    snapshots = item_rows(lab.batch)
    expected = snapshot_fields(original.item)

    forms, rows = native_detail(lab)

    assert len(forms) == len(rows) == 1
    assert forms[0].instance.pk == original.item.pk
    assert forms[0].instance.qr_code_id == original.code.pk
    row = rows[0]
    assert {
        name: unescape(strip_tags(row[name])).strip() for name in SNAPSHOT_COLUMNS
    } == {name: str(expected[name]) for name in SNAPSHOT_COLUMNS}
    assert str(escape(label)) in row["label_text"]
    assert label not in row["label_text"]
    assert "<img" not in row["label_text"]
    url = reverse("admin:boxes_qrcode_change", args=[original.code.pk])
    text = f"{original.code.target_type}:{original.code.target_id} [{original.code.status}]"
    cell = row["qr_code_display"]
    assert f'<a href="{url}">{escape(text)}</a>' in cell
    assert unescape(strip_tags(cell)).strip() == text
    assert "QR unavailable" not in cell
    assert item_rows(lab.batch) == snapshots
