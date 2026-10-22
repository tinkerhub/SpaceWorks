"""Borrower copy names the configured check-in provider and purpose, never a hard-coded one."""

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.checkin.provider import provider_name, required_purpose
from tests.return_helpers import make_space

pytestmark = pytest.mark.django_db

TINKERHUB_URL = "https://app-api.tinkerhub.org/checkin/active"
OTHER_URL = "https://checkin.example.org/active"


@override_settings(CHECKIN_PROVIDER_NAME="", CHECKIN_API_URL=TINKERHUB_URL)
def test_tinkerhub_roster_keeps_its_name_without_a_setting():
    assert provider_name() == "TinkerHub"


@override_settings(CHECKIN_PROVIDER_NAME="", CHECKIN_API_URL=OTHER_URL)
def test_another_upstream_stays_unnamed_until_configured():
    assert provider_name() == ""


@override_settings(CHECKIN_PROVIDER_NAME="  Maker Gate  ", CHECKIN_API_URL=TINKERHUB_URL)
def test_configured_name_wins():
    assert provider_name() == "Maker Gate"


@override_settings(
    CHECKIN_PROVIDER_NAME="Maker Gate",
    CHECKIN_API_URL=OTHER_URL,
    CHECKIN_REQUIRED_PURPOSE="Building something",
)
def test_bootstrap_names_the_provider_and_purpose_only_on_checked_in():
    space = make_space("provider-copy-checkin")
    space.enabled_modules = ["public_inventory", "request_workflow"]
    space.public_request_mode = "checked_in"
    space.checkin_space_id = 1
    space.save()
    other = make_space("provider-copy-accounts")
    other.enabled_modules = ["public_inventory", "request_workflow"]
    other.save()

    checked_in = APIClient().get(f"/api/v1/bootstrap?slug={space.slug}")
    accounts = APIClient().get(f"/api/v1/bootstrap?slug={other.slug}")

    assert checked_in.status_code == accounts.status_code == 200
    assert checked_in.data["makerspace"]["checkin"] == {
        "provider": "Maker Gate",
        "purpose": "Building something",
    }
    assert "checkin" not in accounts.data["makerspace"]
    assert required_purpose() == "Building something"
