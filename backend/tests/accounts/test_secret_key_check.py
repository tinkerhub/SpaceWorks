"""accounts.E001: a placeholder or short SECRET_KEY is refused when DEBUG is False."""

import secrets

import pytest
from django.core.checks import Tags, run_checks
from django.test import override_settings

from apps.accounts.checks import check_secret_key

STRONG = secrets.token_urlsafe(50)


@pytest.mark.parametrize(
    "key",
    [
        "dev-insecure-change-me",
        "replace-with-a-long-random-secret",
        "django-insecure-" + "x1y2z3" * 10,
        "please-CHANGEME-" + "a1b2c3d4" * 6,
        "short-but-random-Q9",
        "a" * 64,
    ],
    ids=["dev-compose", "env-example", "django-insecure", "marker", "short", "few-unique"],
)
def test_insecure_secret_key_is_an_error_without_debug(key):
    with override_settings(DEBUG=False, SECRET_KEY=key):
        errors = check_secret_key(None)

    assert [error.id for error in errors] == ["accounts.E001"]


@pytest.mark.parametrize(
    "key",
    [STRONG, secrets.token_hex(16), "Zm9vYmFyYmF6cXV4cXV1eGNvcmdlZ3JhdWx0Z2FycGx5Cg=="],
    ids=["token-urlsafe-50", "hex-32", "base64-48"],
)
def test_strong_secret_key_passes(key):
    with override_settings(DEBUG=False, SECRET_KEY=key):
        assert check_secret_key(None) == []


def test_debug_mode_allows_the_dev_placeholder():
    with override_settings(DEBUG=True, SECRET_KEY="dev-insecure-change-me"):
        assert check_secret_key(None) == []


def test_check_is_registered_with_the_security_tag():
    with override_settings(DEBUG=False, SECRET_KEY="dev-insecure-change-me"):
        ids = {message.id for message in run_checks(tags=[Tags.security])}
    with override_settings(DEBUG=False, SECRET_KEY=STRONG):
        clean = {message.id for message in run_checks(tags=[Tags.security])}

    assert "accounts.E001" in ids
    assert "accounts.E001" not in clean
