"""The control form explains shared paths and reports domain collisions by field."""

import pytest

from apps.makerspaces.admin_capabilities import MakerspaceAdminForm
from tests.admin_form_helpers import form_data
from tests.return_helpers import make_space

pytestmark = pytest.mark.django_db


def bound(space, domain):
    data = form_data(MakerspaceAdminForm(instance=space))
    data["frontend_domain"] = domain
    return MakerspaceAdminForm(data=data, instance=space)


def test_blank_domain_is_valid_and_help_explains_shared_site():
    form = bound(make_space("form-shared"), "")
    assert form.is_valid(), form.errors
    assert form.cleaned_data["frontend_domain"] is None
    help_text = str(form.fields["frontend_domain"].help_text)
    assert "leave blank" in help_text.lower()
    assert "/m/your-space/admin" in help_text
    assert "unique hostname" in help_text


def test_case_insensitive_duplicate_is_a_friendly_field_error():
    owner = make_space("form-owner")
    owner.frontend_domain = "dedicated.example.test"
    owner.save(update_fields=["frontend_domain"])
    form = bound(make_space("form-other"), "DEDICATED.EXAMPLE.TEST")
    assert not form.is_valid()
    assert "frontend_domain" in form.errors
    assert "belongs to another makerspace" in str(form.errors["frontend_domain"])
    assert "blank" in str(form.errors["frontend_domain"])
    assert not form.non_field_errors()
    owner.refresh_from_db()
    assert owner.frontend_domain == "dedicated.example.test"


def test_same_instance_can_keep_its_domain_with_different_case():
    space = make_space("form-same")
    space.frontend_domain = "own.example.test"
    space.save(update_fields=["frontend_domain"])
    form = bound(space, "OWN.EXAMPLE.TEST")
    assert form.is_valid(), form.errors
    assert form.cleaned_data["frontend_domain"] == "own.example.test"
