"""Synthetic inputs and private, cached real Compose resolution for this contract."""

import base64
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROFILES = {
    "base": "docker-compose.yml",
    "prod": "docker-compose.prod.yml",
    "cloud": "docker-compose.cloud.yml",
}
APP_ROLES = {
    "backend": "backend", "migrate": "migrate", "worker": "worker",
    "beat": "beat", "candidate-backend": "backend",
}
CLOUD_ROLES = {
    "backend": "backend", "migrate": "migrate", "cron": "cron",
    "candidate-backend": "backend",
}
DEFAULTS = {
    "PII_ENCRYPTION_ENABLED": "False",
    "PII_ENCRYPTION_DUAL_READ": "True",
    "PII_KEY_BROKER": "local",
    "PII_MASTER_KEY": "",
    "PII_MASTER_KEY_PREVIOUS": "",
    "PII_SEARCH_HASH_KEY": "",
    "PII_DEK_CACHE_TTL_SECONDS": "300",
    "PII_AWS_KMS_KEY_ID": "",
    "PII_AWS_KMS_REGION": "",
    "PII_AWS_KMS_ENDPOINT_URL": "",
    "HMAC_CLIENT_ID": "",
    "HMAC_SECRET": "",
    "HMAC_MAX_CLOCK_SKEW_SECONDS": "300",
    "APICLIENT_REQUIRE_NONCE": "False",
    "HMAC_PROTECTED_PATH_PREFIXES": "/api/public/,/api/v1/public/",
    "API_CLIENT_AUTH_REQUIRED": "False",
}
# Public deterministic fixtures, never deployment key material. All four differ.
MASTER, PREVIOUS, SEARCH, API_KEY = (
    base64.urlsafe_b64encode(bytes(range(start, start + 32))).decode("ascii")
    for start in (0, 32, 64, 96)
)
CONFIGURED = {
    "PII_ENCRYPTION_ENABLED": "True",
    "PII_ENCRYPTION_DUAL_READ": "False",
    "PII_KEY_BROKER": "local",
    "PII_MASTER_KEY": MASTER,
    "PII_MASTER_KEY_PREVIOUS": PREVIOUS,
    "PII_SEARCH_HASH_KEY": SEARCH,
    "PII_DEK_CACHE_TTL_SECONDS": "91",
    "PII_AWS_KMS_KEY_ID": "alias/public-test-only",
    "PII_AWS_KMS_REGION": "us-east-2",
    "PII_AWS_KMS_ENDPOINT_URL": "https://kms.example.test",
    "HMAC_CLIENT_ID": "public-test-client",
    "HMAC_SECRET": "public-test-hmac-secret",
    "HMAC_MAX_CLOCK_SKEW_SECONDS": "47",
    "APICLIENT_REQUIRE_NONCE": "True",
    "HMAC_PROTECTED_PATH_PREFIXES": "/api/test-only/,/api/second-test-only/",
    "API_CLIENT_AUTH_REQUIRED": "True",
}
REQUIRED = {
    "POSTGRES_PASSWORD": "owner-password",
    "MINIO_ROOT_USER": "minio-user",
    "MINIO_ROOT_PASSWORD": "minio-password",
    "SECRET_KEY": "public-test-only-django-secret-at-least-32-characters",
    "ALLOWED_HOSTS": "localhost",
    "DATABASE_URL": "postgres://app@candidate/candidate",
    "SPACEWORKS_DB_POINTER_GENERATION": "4",
    "SPACEWORKS_MAINTENANCE_DATABASE_URL": "postgres://owner@candidate/candidate",
    "API_CLIENT_ENC_KEY": API_KEY,
    "AWS_ACCESS_KEY_ID": "access",
    "AWS_SECRET_ACCESS_KEY": "secret",
    "AWS_S3_ENDPOINT_URL": "https://storage.internal",
    "AWS_S3_PUBLIC_ENDPOINT_URL": "https://storage.example.test",
    "PUBLIC_APP_BASE_URL": "https://app.example.test",
    "PUBLIC_IMAGE_BASE_URL": "https://storage.example.test/public",
    "DEFAULT_FROM_EMAIL": "noreply@example.test",
}


def scenario(case):
    if case == "default":
        return {}, DEFAULTS.copy()
    if case == "blank":
        return dict.fromkeys(DEFAULTS, ""), DEFAULTS.copy()
    values = CONFIGURED.copy()
    if case == "kms":
        values["PII_KEY_BROKER"] = "aws_kms"
    elif case in {"missing_keys", "invalid_keys"}:
        value = "" if case == "missing_keys" else "public-test-invalid-key"
        values.update(PII_MASTER_KEY=value, PII_SEARCH_HASH_KEY=value)
    elif case == "shared_keys":
        values["PII_SEARCH_HASH_KEY"] = MASTER
    elif case == "off_zero":
        for key in ("PII_ENCRYPTION_ENABLED", "APICLIENT_REQUIRE_NONCE",
                    "API_CLIENT_AUTH_REQUIRED"):
            values[key] = "False"
        values.update(PII_DEK_CACHE_TTL_SECONDS="0", HMAC_MAX_CLOCK_SKEW_SECONDS="0")
    elif case != "configured":
        raise ValueError("Unknown synthetic scenario")
    return values.copy(), values


def private_json(command, environment, label):
    """Never include stdout, stderr, environments or exception text in failures."""
    try:
        result = subprocess.run(
            command, cwd=ROOT, env=environment, capture_output=True,
            text=True, timeout=45, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        pytest.fail(f"{label}: required subprocess unavailable", pytrace=False)
    if result.returncode:
        pytest.fail(f"{label}: subprocess failed", pytrace=False)
    try:
        document = json.loads(result.stdout)
    except (ValueError, TypeError):
        pytest.fail(f"{label}: expected JSON", pytrace=False)
    if not isinstance(document, dict):
        pytest.fail(f"{label}: expected JSON object", pytrace=False)
    return document


@pytest.fixture(scope="session")
def security_env_runtime(tmp_path_factory):
    private = tmp_path_factory.mktemp("security-env-forwarding")
    empty_env = private / "empty.env"
    empty_env.write_text("", encoding="utf-8")
    docker_config = private / "docker-config"
    docker_config.mkdir()
    # PATH locates root-provided tools; no inherited Compose/app/cloud credentials.
    environment = {
        "PATH": os.defpath if "PATH" not in os.environ else os.environ["PATH"],
        "HOME": str(private), "DOCKER_CONFIG": str(docker_config),
        "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
    }
    cache = {}

    def resolve(profile, case):
        cache_key = (profile, case)
        if cache_key not in cache:
            supplied, _ = scenario(case)
            cache[cache_key] = private_json(
                ["docker", "compose", "--project-name", "security-env-contract",
                 "--project-directory", str(ROOT), "--env-file", str(empty_env),
                 "--profile", "host-recovery", "-f", str(ROOT / PROFILES[profile]),
                 "config", "--format", "json"],
                {**environment, **REQUIRED, **supplied}, f"{profile}/Compose",
            )
        return cache[cache_key]

    return resolve, environment


def effective_settings(environment, runtime_environment):
    # Base Compose deliberately does not forward TRUSTED_PROXY_COUNT. Supply only
    # that prerequisite to the settings probe; all 16 target values come from Compose.
    process_environment = {
        **runtime_environment, **environment,
        "TRUSTED_PROXY_COUNT": environment.get("TRUSTED_PROXY_COUNT", "0"),
        "DJANGO_SETTINGS_MODULE": "config.settings",
        "PYTHONPATH": str(ROOT / "backend"),
    }
    return private_json(
        [sys.executable, str(ROOT / "backend/tests/security_env_settings_probe.py")],
        process_environment, "Django/settings",
    )


def assert_settings(actual, expected, label):
    """Report key names only, even if an unexpected setting contains a secret."""
    if set(actual) != set(expected):
        pytest.fail(f"{label}: setting names differ", pytrace=False)
    for key, value in expected.items():
        if type(actual[key]) is not type(value) or actual[key] != value:
            pytest.fail(f"{label}: {key} differs", pytrace=False)
