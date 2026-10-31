"""Direct admin callers cannot borrow changeform_view's tenant-write authority."""

import pytest
from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.contrib.admin.sites import AdminSite
from django.db import connection
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.makerspaces.admin import MakerspaceAdmin
from apps.makerspaces.admin_capabilities import MakerspaceAdminForm, MakerspaceCapabilityAdminMixin
from apps.makerspaces.models import Makerspace
from apps.makerspaces.request_access import ANYONE, MEMBERS, MODE_ANYONE, effective_policy
from apps.tenant_migration.gate_errors import SourceMigrationGateUnavailable
from tests.return_helpers import make_user

pytestmark = pytest.mark.django_db


class CapabilityEditForm(MakerspaceAdminForm):
    # Keep real capability cleaning/before-state capture; unrelated settings are
    # omitted just as ModelAdmin's generated form omits excluded fields.
    class Meta(MakerspaceAdminForm.Meta):
        fields = ("name", "slug", "public_request_mode", "capabilities")


class CapabilityAdmin(MakerspaceCapabilityAdminMixin, admin.ModelAdmin):
    """A real ModelAdmin supplies the mixin's normal model-save implementation."""


@pytest.mark.parametrize("kind", ["registered", "isolated-mixin"])
def test_direct_capability_save_requires_source_boundary(kind):
    actor = make_user(
        "capability-boundary-super", role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE, is_staff=True, is_superuser=True,
    )
    modules = ["public_inventory", "request_workflow", "staff_admin", "scanner",
               "evidence_uploads", "qr_management"]
    space = Makerspace.objects.create(
        name="Boundary required", slug="capability-boundary",
        enabled_modules=modules, enabled_features=[], public_request_mode=MODE_ANYONE,
    )
    assert effective_policy(space) == ANYONE
    maker_before = list(Makerspace.objects.order_by("pk").values())
    audits_before = list(AuditLog.objects.order_by("pk").values())
    history_before = list(LogEntry.objects.order_by("pk").values())

    form = CapabilityEditForm(instance=space, data={
        "name": space.name, "slug": space.slug, "public_request_mode": MODE_ANYONE,
        "capabilities": [f"module:{key}" for key in [*modules, "membership", "member_accounts"]],
    })
    assert form.request_access_before == ANYONE
    assert form.capability_before == {"modules": sorted(modules), "features": []}
    assert form.is_valid(), form.errors
    obj = form.save(commit=False)
    assert "membership" in obj.enabled_modules
    assert effective_policy(obj) == MEMBERS
    assert "capabilities" in form.changed_data
    request = RequestFactory().post(
        reverse("admin:makerspaces_makerspace_change", args=[space.pk]), data=form.data,
    )
    request.user = actor
    if kind == "registered":
        model_admin = admin.site._registry[Makerspace]
        assert isinstance(model_admin, MakerspaceAdmin)
    else:
        model_admin = CapabilityAdmin(Makerspace, AdminSite())

    # Deliberately do not enter boundary_tenant_write. Neither Django's test
    # transaction nor a valid form grants the source boundary held by the view.
    with CaptureQueriesContext(connection) as queries:
        with pytest.raises(SourceMigrationGateUnavailable):
            model_admin.save_model(request, obj, form, change=True)

    assert not any("FOR UPDATE" in query["sql"].upper() for query in queries.captured_queries)
    assert list(Makerspace.objects.order_by("pk").values()) == maker_before
    assert list(AuditLog.objects.order_by("pk").values()) == audits_before
    assert list(LogEntry.objects.order_by("pk").values()) == history_before
    space.refresh_from_db()
    assert effective_policy(space) == ANYONE
    assert space.public_request_mode == MODE_ANYONE
    assert "membership" not in space.enabled_modules
