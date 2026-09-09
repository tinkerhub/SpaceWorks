"""Shared makerspace model helpers with no dependency on the model barrel.

This neutral module is where the makerspace model submodules meet: they may depend
on it without importing the barrel or one another, so every submodule remains safe
to import first.
"""

from urllib.parse import urlsplit

from django.utils.crypto import get_random_string

from apps.makerspaces.validators import DEFAULT_PRESENCE_PRESETS


def generate_publishable_key():
    return f"pk_{get_random_string(32)}"


def generate_domain_verification_token():
    return f"dv_{get_random_string(48)}"


def generate_public_code():
    return get_random_string(4, allowed_chars="ABCDEFGHJKLMNPQRSTUVWXYZ23456789")


def normalize_frontend_domain(value):
    """Reduce a pasted domain/URL/origin to a bare lowercase host (or None).

    A staff member may paste `https://alpha.example/admin`; storing that raw would
    make the origin helpers build `https://https://alpha.example`. Extract just the
    host so `frontend_domain` is always a bare hostname.
    """
    raw = (value or "").strip().lower()
    if not raw:
        return None
    parsed = urlsplit(raw if "://" in raw else f"//{raw}")
    return (parsed.hostname or "") or None


def presence_presets(makerspace):
    """Configured presence lengths, with an empty configuration using the defaults."""
    return makerspace.presence_preset_minutes or list(DEFAULT_PRESENCE_PRESETS)
