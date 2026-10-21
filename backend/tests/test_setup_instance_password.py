"""setup_instance superadmin password rules: there is no shipped default password."""

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

pytestmark = pytest.mark.django_db


def test_setup_instance_refuses_to_create_a_superadmin_without_a_password(monkeypatch):
    """There is no shipped default password; a refused run writes nothing."""
    from django.core.management.base import CommandError

    from apps.makerspaces.models import Makerspace

    monkeypatch.delenv("SETUP_SUPERADMIN_USERNAME", raising=False)
    monkeypatch.delenv("SETUP_SUPERADMIN_PASSWORD", raising=False)

    with pytest.raises(CommandError, match="--password"):
        call_command("setup_instance", makerspace_slug="no-password-space")

    assert not get_user_model().objects.filter(username="superadmin").exists()
    assert not Makerspace.objects.filter(slug="no-password-space").exists()


def test_setup_instance_accepts_the_password_from_the_environment(monkeypatch):
    monkeypatch.delenv("SETUP_SUPERADMIN_USERNAME", raising=False)
    monkeypatch.setenv("SETUP_SUPERADMIN_PASSWORD", "Env-Strong-Password-123")

    call_command("setup_instance")

    user = get_user_model().objects.get(username="superadmin")
    assert user.check_password("Env-Strong-Password-123")
    assert not user.check_password("super123")


def test_setup_instance_rerun_for_an_existing_superadmin_needs_no_password(monkeypatch):
    monkeypatch.delenv("SETUP_SUPERADMIN_USERNAME", raising=False)
    monkeypatch.delenv("SETUP_SUPERADMIN_PASSWORD", raising=False)
    call_command("setup_instance", username="rerun-admin", password="Rerun-Strong-123")

    call_command("setup_instance", username="rerun-admin")

    assert get_user_model().objects.get(username="rerun-admin").check_password("Rerun-Strong-123")


def test_setup_instance_explicit_password_does_not_force_change(monkeypatch):
    monkeypatch.delenv("SETUP_SUPERADMIN_USERNAME", raising=False)
    monkeypatch.delenv("SETUP_SUPERADMIN_PASSWORD", raising=False)

    call_command(
        "setup_instance",
        username="explicit-superadmin",
        password="Explicit-Strong-123",
    )

    user = get_user_model().objects.get(username="explicit-superadmin")
    assert user.must_change_password is False
    assert user.check_password("Explicit-Strong-123")
