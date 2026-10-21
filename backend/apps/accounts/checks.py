"""Refuse a placeholder or short SECRET_KEY on a non-DEBUG deployment.

SECRET_KEY signs sessions and JWTs and keys every HMAC fingerprint in `accounts`
(claim codes, password-reset tokens, device and social nonces). A value copied from
an example file is public, so a production process must not start with one. This is
an Error rather than Django's deploy-only W009: `migrate` runs it, so an update with
a bad key fails before the new release starts and `update.sh` rolls back.
"""

from django.conf import settings
from django.core.checks import Error, Tags, register

# The values this repository ships in its example env files and dev compose.
PLACEHOLDER_SECRET_KEYS = frozenset({
    "dev-insecure-change-me",
    "replace-with-a-long-random-secret",
})
PLACEHOLDER_MARKERS = ("change-me", "changeme", "replace-with", "insecure")
# 32 characters keeps common generators valid (`openssl rand -base64 32` is 44,
# `openssl rand -hex 16` is 32); the installers write 50.
MIN_SECRET_KEY_LENGTH = 32
MIN_SECRET_KEY_UNIQUE_CHARACTERS = 5


def secret_key_problem(secret_key):
    key = secret_key or ""
    lowered = key.lower()
    if key in PLACEHOLDER_SECRET_KEYS or any(marker in lowered for marker in PLACEHOLDER_MARKERS):
        return "is a placeholder value"
    if len(key) < MIN_SECRET_KEY_LENGTH:
        return f"is shorter than {MIN_SECRET_KEY_LENGTH} characters"
    if len(set(key)) < MIN_SECRET_KEY_UNIQUE_CHARACTERS:
        return f"has fewer than {MIN_SECRET_KEY_UNIQUE_CHARACTERS} distinct characters"
    return None


@register(Tags.security)
def check_secret_key(app_configs, **kwargs):
    if settings.DEBUG:
        return []
    problem = secret_key_problem(settings.SECRET_KEY)
    if problem is None:
        return []
    return [
        Error(
            f"SECRET_KEY {problem} and DEBUG is False.",
            hint=(
                "Set SECRET_KEY to a long random value, e.g. "
                "python -c \"import secrets; print(secrets.token_urlsafe(50))\"."
            ),
            id="accounts.E001",
        )
    ]
