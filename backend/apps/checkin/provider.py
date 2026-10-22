"""How borrower-facing copy names the upstream check-in system and its required purpose.

Both come from settings so a makerspace on another check-in provider never sees the
reference deployment's names. The provider name falls back to "TinkerHub" only when the
roster URL is TinkerHub's own, so existing TinkerHub-backed installs keep their wording
without a new setting; any other upstream gets neutral copy until it is named.
"""

from urllib.parse import urlparse

from django.conf import settings


def provider_name() -> str:
    configured = (getattr(settings, "CHECKIN_PROVIDER_NAME", "") or "").strip()
    if configured:
        return configured
    host = (urlparse(getattr(settings, "CHECKIN_API_URL", "") or "").hostname or "").lower()
    if host == "tinkerhub.org" or host.endswith(".tinkerhub.org"):
        return "TinkerHub"
    return ""


def required_purpose() -> str:
    return (getattr(settings, "CHECKIN_REQUIRED_PURPOSE", "") or "").strip()
