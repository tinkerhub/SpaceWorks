"""Real Compose interpolation -> process environment -> real Django settings."""

import pytest

from tests.security_env_forwarding_helpers import (
    APP_ROLES, CLOUD_ROLES, DEFAULTS, PROFILES, REQUIRED, assert_settings,
    effective_settings, scenario, security_env_runtime,
)

CASES = ("default", "blank", "configured", "off_zero", "kms")
BOOL_KEYS = {
    "PII_ENCRYPTION_ENABLED", "PII_ENCRYPTION_DUAL_READ",
    "APICLIENT_REQUIRE_NONCE", "API_CLIENT_AUTH_REQUIRED",
}
INT_KEYS = {"PII_DEK_CACHE_TTL_SECONDS", "HMAC_MAX_CLOCK_SKEW_SECONDS"}


def typed_settings(expected):
    values = expected.copy()
    for key in BOOL_KEYS:
        values[key] = values[key] == "True"
    for key in INT_KEYS:
        values[key] = int(values[key])
    values["HMAC_PROTECTED_PATH_PREFIXES"] = values["HMAC_PROTECTED_PATH_PREFIXES"].split(",")
    return values


def application_environments(document, profile):
    roles = CLOUD_ROLES if profile == "cloud" else APP_ROLES
    services = document.get("services", {})
    actual_apps = {
        name for name, service in services.items()
        if (service.get("command") or [])[:1] == ["--role"]
    }
    if actual_apps != set(roles):
        pytest.fail(f"{profile}: application service names differ", pytrace=False)
    for name, role in roles.items():
        service = services[name]
        if service["command"][:2] != ["--role", role]:
            pytest.fail(f"{profile}/{name}: role differs", pytrace=False)
        yield name, service.get("environment", {})


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("case", CASES)
def test_exact_forwarding_and_process_effective_settings(security_env_runtime, profile, case):
    resolve, runtime_environment = security_env_runtime
    _, expected = scenario(case)
    document = resolve(profile, case)
    for name, environment in application_environments(document, profile):
        forwarded = {key: environment[key] for key in DEFAULTS if key in environment}
        assert_settings(forwarded, expected, f"{profile}/{name}/environment")
        result = effective_settings(environment, runtime_environment)
        assert_settings(result.get("settings", {}), typed_settings(expected), f"{profile}/{name}")
        if result.get("python") != [3, 12]:
            pytest.fail(f"{profile}/{name}: Python version differs", pytrace=False)
        # KMS is settings forwarding only: no optional provider/IAM success claim.
        expected_errors = None if case == "kms" else []
        if result.get("wrapping_errors") != expected_errors:
            pytest.fail(f"{profile}/{name}: wrapping check result differs", pytrace=False)


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("case", CASES)
def test_bootstrap_and_probe_environment_stays_minimal(security_env_runtime, profile, case):
    resolve, _ = security_env_runtime
    services = resolve(profile, case)["services"]
    owner_url = {
        "base": "postgres://makerspace:makerspace@db:5432/makerspace_manager",
        "prod": "postgres://makerspace:owner-password@db:5432/makerspace_manager",
        "cloud": REQUIRED["SPACEWORKS_MAINTENANCE_DATABASE_URL"],
    }[profile]
    expected = {
        "DATABASE_URL": owner_url,
        "SPACEWORKS_RUNTIME_DATABASE_URL": REQUIRED["DATABASE_URL"],
        "SPACEWORKS_HOST_MARKER_WRITE_PATH": "/host-state/restore-marker.json",
        "SPACEWORKS_SCHEDULER_MODE": "image",
        "SPACEWORKS_SCHEDULER_SERVICES": "cron" if profile == "cloud" else "beat",
    }
    for name in ("orchestration-init", "orchestration-ready"):
        service = services[name]
        if service.get("entrypoint") != ["python", "/app/scripts/bootstrap_host_orchestration.py"]:
            pytest.fail(f"{profile}/{name}: bootstrap entrypoint differs", pytrace=False)
        assert_settings(service.get("environment", {}), expected, f"{profile}/{name}")


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("case,expected_errors", [
    ("missing_keys", ["encryption.E001", "encryption.E006"]),
    ("invalid_keys", ["encryption.E001", "encryption.E006"]),
    ("shared_keys", ["encryption.E005"]),
])
def test_enabled_local_wrapping_refuses_bad_keys(
    security_env_runtime, profile, case, expected_errors,
):
    resolve, runtime_environment = security_env_runtime
    environment = resolve(profile, case)["services"]["backend"]["environment"]
    _, expected = scenario(case)
    forwarded = {key: environment[key] for key in DEFAULTS if key in environment}
    assert_settings(forwarded, expected, f"{profile}/backend/environment")
    result = effective_settings(environment, runtime_environment)
    assert_settings(result.get("settings", {}), typed_settings(expected), f"{profile}/backend")
    if result.get("wrapping_errors") != expected_errors:
        pytest.fail(f"{profile}/backend: expected wrapping error IDs differ", pytrace=False)
