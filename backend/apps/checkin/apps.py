from django.apps import AppConfig
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class CheckinConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.checkin"

    def ready(self):
        validate_settings()


def validate_settings():
    """Refuse to boot on a half-configured DEPLOYMENT default.

    Only the environment is checked here, never the database: `ready()` must not
    query, and a makerspace's own roster settings are validated when they are saved.
    A makerspace in `checked_in` mode whose roster resolves to nothing fails closed at
    request time with a 503 (`client.fetch_roster`), which is the right blast radius
    for one tenant's configuration -- not a deployment that will not start.
    """
    # The timeout governs every roster fetch, including a makerspace's own URL on a
    # deployment that never set CHECKIN_API_URL, so it is checked unconditionally.
    timeout = getattr(settings, "CHECKIN_TIMEOUT", None)
    if timeout is None or timeout <= 0:
        raise ImproperlyConfigured("CHECKIN_TIMEOUT must be a positive number.")
    if not (getattr(settings, "CHECKIN_API_URL", "") or "").strip():
        # Blank is a valid, complete state: the deployment offers no default roster.
        # A makerspace may still bring its own, and its own blank purpose then falls
        # back to CHECKIN_REQUIRED_PURPOSE (default "Working on a project").
        return
    if not (getattr(settings, "CHECKIN_REQUIRED_PURPOSE", "") or "").strip():
        raise ImproperlyConfigured(
            "CHECKIN_REQUIRED_PURPOSE must be non-blank when CHECKIN_API_URL is set. "
            "A blank required purpose would admit every checked-in person."
        )
