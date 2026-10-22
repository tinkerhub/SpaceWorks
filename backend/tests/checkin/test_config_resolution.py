"""Per-makerspace check-in configuration: resolution order, startup check, bootstrap copy."""

from types import SimpleNamespace

import pytest
from django.core.exceptions import ImproperlyConfigured
from rest_framework.test import APIClient

from apps.checkin.apps import validate_settings
from apps.checkin.config import checkin_config
from apps.makerspaces.models import Makerspace

ENV_URL = "https://checkin.example.org/active"
TINKERHUB_URL = "https://app-api.tinkerhub.org/checkin/active"


def _ms(url="", purpose="", provider=""):
    return SimpleNamespace(
        checkin_api_url=url, checkin_required_purpose=purpose, checkin_provider_name=provider
    )


@pytest.fixture
def env(settings):
    settings.CHECKIN_API_URL = ENV_URL
    settings.CHECKIN_REQUIRED_PURPOSE = "Working on a project"
    settings.CHECKIN_PROVIDER_NAME = "Maker Gate"
    return settings


def test_blank_makerspace_values_resolve_to_the_deployment_exactly(env):
    """The production shape: no per-makerspace values, today's behaviour."""
    for makerspace in (None, _ms()):
        config = checkin_config(makerspace)
        assert (config.url, config.purpose, config.provider, config.tenant_url) == (
            ENV_URL, "Working on a project", "Maker Gate", False
        )


def test_each_own_value_wins_over_the_deployment(env):
    config = checkin_config(
        _ms("https://roster.example.net/now", " Building ", " Space Pass ")
    )
    assert config.url == "https://roster.example.net/now"
    assert config.purpose == "Building"
    assert config.provider == "Space Pass"
    assert config.tenant_url is True


def test_fields_fall_back_independently(env):
    config = checkin_config(_ms(purpose="Tinkering"))
    assert (config.url, config.purpose, config.tenant_url) == (ENV_URL, "Tinkering", False)
    assert config.provider == "Maker Gate"


def test_own_url_does_not_inherit_the_deployment_provider_name(env):
    """The deployment's name belongs to the deployment's roster, not this one."""
    assert checkin_config(_ms("https://roster.example.net/now")).provider == ""
    assert checkin_config(_ms(TINKERHUB_URL)).provider == "TinkerHub"


def test_deployment_provider_falls_back_to_the_tinkerhub_host(settings):
    settings.CHECKIN_API_URL = TINKERHUB_URL
    settings.CHECKIN_PROVIDER_NAME = ""
    assert checkin_config(_ms()).provider == "TinkerHub"


def test_nothing_configured_is_not_ready(settings):
    settings.CHECKIN_API_URL = ""
    config = checkin_config(_ms())
    assert config.url == "" and not config.ready


def test_blank_purpose_everywhere_is_not_ready(settings):
    settings.CHECKIN_API_URL = ""
    settings.CHECKIN_REQUIRED_PURPOSE = ""
    assert not checkin_config(_ms("https://roster.example.net/now")).ready


# --- startup check ------------------------------------------------------------


def test_startup_requires_a_purpose_when_the_deployment_url_is_set(settings):
    settings.CHECKIN_API_URL = ENV_URL
    settings.CHECKIN_REQUIRED_PURPOSE = "  "
    with pytest.raises(ImproperlyConfigured, match="CHECKIN_REQUIRED_PURPOSE"):
        validate_settings()


def test_startup_accepts_no_deployment_roster(settings):
    """Per-makerspace URLs may exist; blank env is complete and boots."""
    settings.CHECKIN_API_URL = ""
    settings.CHECKIN_REQUIRED_PURPOSE = ""
    validate_settings()


@pytest.mark.parametrize("url", ["", ENV_URL])
def test_startup_refuses_a_non_positive_timeout_with_or_without_a_url(settings, url):
    settings.CHECKIN_API_URL = url
    settings.CHECKIN_TIMEOUT = 0
    with pytest.raises(ImproperlyConfigured, match="CHECKIN_TIMEOUT"):
        validate_settings()


def test_startup_passes_the_production_shape(env):
    validate_settings()


# --- bootstrap ----------------------------------------------------------------


@pytest.mark.django_db
def test_bootstrap_names_each_makerspaces_own_provider_and_purpose(env):
    modules = ["public_inventory", "request_workflow"]
    own = Makerspace.objects.create(
        name="own", slug="cfg-own", enabled_modules=modules,
        public_request_mode="checked_in", checkin_space_id=1,
        checkin_api_url="https://roster.example.net/now",
        checkin_required_purpose="Building", checkin_provider_name="Space Pass",
    )
    inherited = Makerspace.objects.create(
        name="inherited", slug="cfg-inherited", enabled_modules=modules,
        public_request_mode="checked_in", checkin_space_id=2,
    )

    own_payload = APIClient().get(f"/api/v1/bootstrap?slug={own.slug}").data
    inherited_payload = APIClient().get(f"/api/v1/bootstrap?slug={inherited.slug}").data

    assert own_payload["makerspace"]["checkin"] == {"provider": "Space Pass", "purpose": "Building"}
    assert inherited_payload["makerspace"]["checkin"] == {
        "provider": "Maker Gate",
        "purpose": "Working on a project",
    }
