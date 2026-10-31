"""Capability admin exercises the actual source boundary before Django row writes."""
import json

import pytest
from django import forms
from django.contrib.admin.models import LogEntry
from django.test import Client
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.makerspaces.models import Makerspace, ModulePurgeReceipt
from apps.makerspaces.module_registry import core_module_keys
from tests.makerspaces.module_cleanup_support import actor, module_receipt, module_space, module_store


def capability_post(client, space):
    target = reverse("admin:makerspaces_makerspace_change", args=[space.pk])
    response = client.get(target)
    assert response.status_code == 200
    form = response.context["adminform"].form
    data = {"_save": "Save", "capabilities": ["module:events", "module:membership"],
            "csrfmiddlewaretoken": client.cookies["csrftoken"].value}
    for name, field in form.fields.items():
        if name == "capabilities" or isinstance(field, forms.FileField):
            continue
        value = form[name].value()
        if isinstance(field, forms.BooleanField):
            if value:
                data[name] = "on"
        elif isinstance(field, forms.JSONField):
            data[name] = value if isinstance(value, str) else json.dumps(value)
        elif field.required and value is not None:
            data[name] = field.prepare_value(value)
    for inline in response.context["inline_admin_formsets"]:
        formset = inline.formset
        for name, field in formset.management_form.fields.items():
            data[f"{formset.prefix}-{name}"] = formset.management_form[name].value()
        # No member rows are present; default roles are not inline memberships.
        assert formset.initial_form_count() == 0
        data[f"{formset.prefix}-TOTAL_FORMS"] = 0
    return target, data


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("completed", [False, True], ids=["pending-refuses", "completed-invalidates"])
def test_actual_native_admin_capability_post_obeys_receipt_enable_barrier(completed, module_store):
    space, user = module_space(storage_bytes_used=12345), actor()
    row = module_receipt(space, completed=completed)
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    target, data = capability_post(client, space)
    maker_before = Makerspace.objects.values().get(pk=space.pk)
    receipt_before = ModulePurgeReceipt.objects.values().get(pk=row.pk)
    audit_count = AuditLog.objects.count()
    capability_audits = AuditLog.objects.filter(
        makerspace=space, action="makerspace.capabilities_changed",
    )
    capability_audit_count = capability_audits.count()
    control_audits = AuditLog.objects.filter(
        action="control.object_updated", target_type="makerspaces.makerspace", target_id=str(space.pk),
    )
    control_audit_count = control_audits.count()
    admin_log_count = LogEntry.objects.count()

    # Valid dependency flags must reach the purge-intent check, not fail normalization.
    response = client.post(target, data)
    form_errors = response.context["adminform"].form.errors if response.status_code == 200 else None
    assert response.status_code == (302 if completed else 200), form_errors
    maker_after = Makerspace.objects.values().get(pk=space.pk)
    receipt_after = ModulePurgeReceipt.objects.values().get(pk=row.pk)
    if completed:
        assert maker_after["enabled_modules"] == sorted(core_module_keys() | {"events", "membership"})
        assert maker_after["enabled_features"] == []
        assert maker_after["storage_bytes_used"] == maker_before["storage_bytes_used"]
        assert receipt_after["invalidated_at"] is not None
        assert receipt_after["invalidation_reason"] == "module_enabled"
        # Only revocation changes: frozen authority and every cleanup checkpoint survive.
        assert receipt_after == {
            **receipt_before,
            "invalidated_at": receipt_after["invalidated_at"],
            "invalidation_reason": "module_enabled",
        }
        assert receipt_after["graph_purged_at"] is not None
        assert capability_audits.count() == capability_audit_count + 1
        assert control_audits.count() == control_audit_count + 1
        assert AuditLog.objects.count() == audit_count + 2
        assert LogEntry.objects.count() == admin_log_count + 1
    else:
        assert set(form_errors) == {"capabilities"}, form_errors
        assert list(form_errors["capabilities"]) == [
            "Finish the module purge intent before reinstalling this module."
        ], form_errors
        # Compare persisted rows, including flags, lifecycle state, quota and timestamps.
        assert maker_after == maker_before
        assert receipt_after == receipt_before
        assert capability_audits.count() == capability_audit_count
        assert control_audits.count() == control_audit_count
        assert AuditLog.objects.count() == audit_count
        assert LogEntry.objects.count() == admin_log_count
    assert module_store.calls == []
    assert module_store.objects == {}
