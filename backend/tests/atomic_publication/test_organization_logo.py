"""The global organization admin cannot introduce an unguarded public-key claim."""
import pytest
from django.contrib import admin
from django.test import RequestFactory

from apps.accounts.models import User
from apps.organizations.models import Organization

pytestmark = pytest.mark.django_db


def test_organization_admin_logo_readonly_preserves_value_against_crafted_post():
    actor = User.objects.create_superuser(username="atomic-org-admin", email="admin@example.test", password="unused")
    org = Organization.objects.create(name="Original", slug="atomic-org", logo_key="retained/logo.png")
    model_admin = admin.site._registry[Organization]
    request = RequestFactory().post("/control/organizations/organization/", {
        "name": "Changed", "slug": org.slug, "logo_key": "stolen/key.png", "is_active": "on",
    })
    request.user = actor
    form_class = model_admin.get_form(request, org)
    form = form_class(data=request.POST, instance=org)
    assert "logo_key" not in form.fields
    assert form.is_valid(), form.errors
    changed = form.save(commit=False)
    model_admin.save_model(request, changed, form, change=True)
    org.refresh_from_db()
    assert org.name == "Changed" and org.logo_key == "retained/logo.png"
