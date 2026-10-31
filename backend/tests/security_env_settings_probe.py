"""Child-only settings/wrapping probe; never starts the deployment app registry."""

import importlib
import json
import sys
from unittest.mock import patch


def probe():
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("Python 3.12 required")

    def no_external_io(event, args):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.bind"}:
            raise RuntimeError("Network forbidden in settings probe")
        if event == "open" and str(args[0]).endswith(".env"):
            raise RuntimeError("Dotenv forbidden in settings probe")

    sys.addaudithook(no_external_io)
    # The production loader unconditionally reads backend/.env. Suppress only
    # that file input; preserve actual settings parsing and all key validators.
    with patch("environ.Env.read_env") as dotenv:
        from django.conf import settings

        names = (
            "PII_ENCRYPTION_ENABLED", "PII_ENCRYPTION_DUAL_READ", "PII_KEY_BROKER",
            "PII_MASTER_KEY", "PII_MASTER_KEY_PREVIOUS", "PII_SEARCH_HASH_KEY",
            "PII_DEK_CACHE_TTL_SECONDS", "PII_AWS_KMS_KEY_ID", "PII_AWS_KMS_REGION",
            "PII_AWS_KMS_ENDPOINT_URL", "HMAC_CLIENT_ID", "HMAC_SECRET",
            "HMAC_MAX_CLOCK_SKEW_SECONDS", "APICLIENT_REQUIRE_NONCE",
            "HMAC_PROTECTED_PATH_PREFIXES", "API_CLIENT_AUTH_REQUIRED",
        )
        values = {name: getattr(settings, name) for name in names}
        if dotenv.call_count != 1:
            raise RuntimeError("Expected one isolated dotenv loader")

    errors = None
    if settings.PII_KEY_BROKER == "local":
        from django.apps import AppConfig, apps
        from django.db.backends.base.base import BaseDatabaseWrapper

        def no_database(*args, **kwargs):
            raise RuntimeError("Database forbidden in wrapping probe")

        # A base AppConfig loads the real encryption models needed by search_key.
        # No project ready() hooks, django.setup(), DB readiness or provider calls.
        config = AppConfig("apps.encryption", importlib.import_module("apps.encryption"))
        with patch.object(BaseDatabaseWrapper, "ensure_connection", no_database):
            apps.populate([config])
            from apps.encryption.checks import check_pii_wrapping_configuration

            errors = sorted(error.id for error in check_pii_wrapping_configuration(None))
    return {"settings": values, "wrapping_errors": errors, "python": [3, 12]}


if __name__ == "__main__":
    try:
        result = probe()
    except Exception as error:
        # Never serialize exception messages or tracebacks containing configuration.
        print(json.dumps({"probe_error": type(error).__name__}))
        sys.exit(1)
    print(json.dumps(result))
