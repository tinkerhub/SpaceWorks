"""Which roster, purpose and provider name a makerspace's check-in gate uses.

The ONE resolver. Every surface that reads the roster or quotes its rules -- lookup,
submit, self-checkout, machine-job requests, the bootstrap copy, the deliberate
request-access writer and the console's test button -- asks this module with the
makerspace in hand, so no path can silently fall back to a different upstream.

Resolution, per field: the makerspace's own value when it set one, otherwise the
deployment setting. Two refinements, both deliberate:

* **Provider name does not inherit across upstreams.** A makerspace that brought its
  own roster URL is on a different check-in system from the one the deployment's
  ``CHECKIN_PROVIDER_NAME`` names, so it falls back to the host heuristic on ITS URL
  (TinkerHub for a TinkerHub host, neutral copy otherwise) rather than borrowing a
  name that would tell borrowers to look in the wrong app.
* **Only a makerspace-supplied URL is attacker-influenced.** ``tenant_url`` tells the
  transport to fetch it through the outbound SSRF guard; the deployment URL is
  operator-controlled and keeps its original transport unchanged.

A deployment with no per-makerspace values (the reference production install)
resolves to exactly the settings it read before this module existed.
"""

from dataclasses import dataclass
from urllib.parse import urlparse

from django.conf import settings


@dataclass(frozen=True, slots=True)
class CheckinConfig:
    url: str
    purpose: str
    provider: str
    # True when `url` is the makerspace's own value, typed by a Space Manager.
    tenant_url: bool

    @property
    def ready(self) -> bool:
        """A roster to read and a purpose to require. Anything less fails closed."""
        return bool(self.url and self.purpose)


def _clean(value) -> str:
    return (value or "").strip() if isinstance(value, str) else ""


def deployment_url() -> str:
    return _clean(getattr(settings, "CHECKIN_API_URL", ""))


def deployment_purpose() -> str:
    return _clean(getattr(settings, "CHECKIN_REQUIRED_PURPOSE", ""))


def deployment_provider() -> str:
    return _clean(getattr(settings, "CHECKIN_PROVIDER_NAME", ""))


def host_provider(url: str) -> str:
    """'TinkerHub' for a TinkerHub roster host, otherwise '' (neutral copy)."""
    host = (urlparse(url or "").hostname or "").lower()
    if host == "tinkerhub.org" or host.endswith(".tinkerhub.org"):
        return "TinkerHub"
    return ""


def checkin_config(makerspace=None) -> CheckinConfig:
    """The resolved check-in configuration for `makerspace` (None: the deployment's)."""
    own_url = _clean(getattr(makerspace, "checkin_api_url", ""))
    own_purpose = _clean(getattr(makerspace, "checkin_required_purpose", ""))
    own_provider = _clean(getattr(makerspace, "checkin_provider_name", ""))

    url = own_url or deployment_url()
    if own_provider:
        provider = own_provider
    elif own_url:
        provider = host_provider(own_url)
    else:
        provider = deployment_provider() or host_provider(url)
    return CheckinConfig(
        url=url,
        purpose=own_purpose or deployment_purpose(),
        provider=provider,
        tenant_url=bool(own_url),
    )
