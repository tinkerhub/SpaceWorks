from django.apps import AppConfig
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class CheckinConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.checkin"

    def ready(self):
        # Validated at startup rather than at first request. A makerspace can only
        # select the `checked_in` request mode once an operator has configured the
        # upstream roster, and a deployment that half-configured it must refuse to
        # boot rather than serve 503s to every public requester.
        url = getattr(settings, "CHECKIN_API_URL", "")
        if not url:
            # Blank is a valid, complete state: no tenant can be in `checked_in` mode
            # without it, which `request_access` enforces separately.
            return
        timeout = getattr(settings, "CHECKIN_TIMEOUT", None)
        if timeout is None or timeout <= 0:
            raise ImproperlyConfigured(
                "CHECKIN_TIMEOUT must be a positive number when CHECKIN_API_URL is set."
            )
        if not getattr(settings, "CHECKIN_REQUIRED_PURPOSE", "").strip():
            raise ImproperlyConfigured(
                "CHECKIN_REQUIRED_PURPOSE must be non-blank when CHECKIN_API_URL is set. "
                "A blank required purpose would admit every checked-in person."
            )
