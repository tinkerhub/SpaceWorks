"""Fetching the raw roster body, fail-closed.

Two transports, chosen by WHO typed the URL (`CheckinConfig.tenant_url`):

* **The deployment URL** (`CHECKIN_API_URL`) is operator-controlled and keeps its
  original transport byte for byte: ``requests.get`` with redirects off, streamed and
  size-capped on the decoded bytes.
* **A makerspace URL** is typed by a Space Manager, so it is attacker-influenced input
  to a server-side fetch. It goes through the SAME outbound guard as tenant webhooks
  (`integrations.webhook_validation`): https only, no embedded credentials, DNS
  resolved once and refused if ANY answer is loopback/private/link-local (which covers
  the 169.254.169.254 metadata service)/CGNAT/reserved, and the connection is pinned
  to the vetted address so a second DNS answer cannot rebind it. Redirects are never
  followed -- a 3xx is "unavailable", so a public host cannot bounce the fetch inward.

Every failure is `CheckinUnavailable` (503 upstream, a readable reason in the console's
test button) and never a denial. `reason` is a stable code for that test button; the
message stays the one the request surfaces have always used.
"""

import http.client
import logging
import ssl

from django.conf import settings

from apps.integrations.webhook_validation import UnsafeWebhookUrl, resolve_webhook_target
from apps.integrations.webhooks import _PinnedHTTPSConnection

logger = logging.getLogger(__name__)

REASON_NOT_CONFIGURED = "not_configured"
REASON_REFUSED = "refused_address"
REASON_UNREACHABLE = "unreachable"
REASON_TIMEOUT = "timeout"
REASON_TLS = "tls"
REASON_STATUS = "http_status"
REASON_REDIRECT = "redirect"
REASON_TOO_LARGE = "too_large"


class CheckinUnavailable(Exception):
    """We could not establish who is checked in. Always maps to 503, never 403."""

    def __init__(self, message="Check-in service is unavailable.", *, reason=REASON_UNREACHABLE):
        super().__init__(message)
        self.reason = reason


def setting(name, default):
    value = getattr(settings, name, default)
    return default if value is None else value


def fetch_body(config):
    if not config.url:
        # A tenant in `checked_in` mode with neither its own roster nor a deployment
        # one. Fail closed rather than admit everyone.
        raise CheckinUnavailable(
            "Check-in service is not configured.", reason=REASON_NOT_CONFIGURED
        )
    if config.tenant_url:
        return _guarded_body(config.url)
    return _deployment_body(config.url)


def tenant_url_error(value) -> str:
    """'' when `value` is a public https roster URL, else a readable refusal.

    The save-time half of the guard; `_guarded_body` repeats it at fetch time, because
    DNS can change between the two.
    """
    try:
        resolve_webhook_target(value)
    except UnsafeWebhookUrl as exc:
        return _refusal_text(str(exc))
    return ""


def _refusal_text(message):
    if "non-public" in message or "invalid address" in message:
        return "That address is private or internal. Use the roster's public https:// URL."
    if "could not be resolved" in message:
        return "The roster's host name could not be found."
    if "credentials" in message:
        return "The roster URL must not contain a username or password."
    if "fragment" in message:
        return "The roster URL must not contain a #fragment."
    if "port" in message:
        return "The roster URL has an invalid port."
    return "Enter the roster's full https:// URL."


def _too_large():
    return CheckinUnavailable("Check-in roster is too large.", reason=REASON_TOO_LARGE)


def _status_failure(status_code):
    logger.warning(
        "Check-in roster returned an unsuccessful status.",
        extra={"status_code": status_code},
    )
    reason = REASON_REDIRECT if 300 <= status_code < 400 else REASON_STATUS
    return CheckinUnavailable("Check-in service is unavailable.", reason=reason)


def _transport_failure(exc, reason):
    # Class name only: an exception message can carry the URL or response text.
    logger.warning("Check-in roster fetch failed.", extra={"error_class": type(exc).__name__})
    return CheckinUnavailable("Check-in service is unavailable.", reason=reason)


def _deployment_body(url):
    import requests

    max_bytes = setting("CHECKIN_MAX_RESPONSE_BYTES", 1_048_576)
    try:
        response = requests.get(
            url,
            timeout=setting("CHECKIN_TIMEOUT", 5.0),
            stream=True,
            allow_redirects=False,
        )
        if not 200 <= response.status_code < 300:
            raise _status_failure(response.status_code)
        declared = int(response.headers.get("Content-Length") or 0)
        if not response.headers.get("Content-Encoding") and declared > max_bytes:
            raise _too_large()
        chunks = []
        size = 0
        # requests asks urllib3 to decode Content-Encoding while iterating. Enforce
        # the ceiling on those decoded bytes, not the smaller compressed wire body.
        for chunk in response.iter_content(chunk_size=min(65_536, max_bytes + 1)):
            if not chunk:
                continue
            if len(chunk) > max_bytes - size:
                raise _too_large()
            chunks.append(chunk)
            size += len(chunk)
        return b"".join(chunks)
    except CheckinUnavailable:
        raise
    except requests.exceptions.Timeout as exc:
        raise _transport_failure(exc, REASON_TIMEOUT) from exc
    except Exception as exc:
        # `requests` raises a wide family here (ConnectionError, SSLError,
        # ChunkedEncodingError, and response-decoding errors). They all mean the
        # same thing to us, and none of them may become a denial.
        raise _transport_failure(exc, REASON_UNREACHABLE) from exc


def _guarded_body(url):
    try:
        target = resolve_webhook_target(url)
    except UnsafeWebhookUrl as exc:
        logger.warning("Check-in roster URL was refused by the outbound guard.")
        raise CheckinUnavailable(
            "Check-in roster address is not allowed.", reason=REASON_REFUSED
        ) from exc

    max_bytes = setting("CHECKIN_MAX_RESPONSE_BYTES", 1_048_576)
    last_error = None
    for address in target.addresses:
        connection = _PinnedHTTPSConnection(target, address)
        # The pinned connection reuses the webhook timeout; the roster has its own.
        connection.timeout = setting("CHECKIN_TIMEOUT", 5.0)
        try:
            connection.request(
                "GET",
                target.request_target,
                headers={
                    "Host": target.host_header,
                    "Accept": "application/json",
                    # Undecoded bytes are what the size cap below measures.
                    "Accept-Encoding": "identity",
                },
            )
            return _read_capped(connection.getresponse(), max_bytes)
        except CheckinUnavailable:
            raise
        except TimeoutError as exc:
            # Never retry the next address on a timeout: N addresses would multiply
            # the time a borrower waits for an answer that is already "unavailable".
            raise _transport_failure(exc, REASON_TIMEOUT) from exc
        except (OSError, http.client.HTTPException) as exc:
            last_error = exc
        finally:
            connection.close()
    reason = REASON_TLS if isinstance(last_error, ssl.SSLError) else REASON_UNREACHABLE
    raise _transport_failure(last_error or OSError(), reason)


def _read_capped(response, max_bytes):
    if not 200 <= response.status < 300:
        raise _status_failure(response.status)
    try:
        declared = int(response.getheader("Content-Length") or 0)
    except ValueError:
        declared = 0
    if declared > max_bytes:
        raise _too_large()
    body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise _too_large()
    return body
