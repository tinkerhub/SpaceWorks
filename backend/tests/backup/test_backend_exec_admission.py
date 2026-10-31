"""Real admission over the existing real Linux Compose producer fixture.

Run on Linux alongside test_recovery_compose_inheritance.py using its documented
host-only pytest invocation. No admission helper/regex or topology guard is mocked.
"""

import pytest

from apps.backup.host_restore_admission import admit_configuration, inventory
from apps.backup.host_restore_transport import RestoreHostError
from tests.backup.recovery_compose_inheritance_support import (
    COMMANDS, DIGEST, SyntheticInspectTransport, render_committed_compose,
)


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    return render_committed_compose(tmp_path_factory.mktemp("backend-exec-admission"))


@pytest.fixture
def transport(rendered):
    return SyntheticInspectTransport(rendered)


def command(*, use_exec=True, workers="3", timeout="60"):
    prefix = "python manage.py collectstatic --noinput && "
    body = (prefix + ("exec " if use_exec else "")
        + "gunicorn config.wsgi:application --bind 0.0.0.0:8000 "
        + f"--workers {workers} --timeout {timeout} --graceful-timeout 30 "
        + "--max-requests 1000 --max-requests-jitter 100 --access-logfile - --error-logfile -")
    return ["--role", "backend", "sh", "-c", body]


@pytest.mark.parametrize("use_exec", [False, True], ids=["legacy", "exec"])
@pytest.mark.parametrize("workers", ["1", "3"])
@pytest.mark.parametrize("timeout", ["60", "120"])
def test_legacy_and_exec_commands_reach_real_admission_and_inventory(transport, use_exec, workers, timeout):
    argv = command(use_exec=use_exec, workers=workers, timeout=timeout)
    transport.config["services"]["backend"]["command"] = argv.copy()
    transport.containers["backend"]["Config"]["Cmd"] = argv.copy()
    assert admit_configuration(transport) == DIGEST
    assert len(inventory(transport)) == 7


def test_actual_producer_fixture_tracks_corrected_compose_independently(transport):
    assert COMMANDS["backend"] == command()
    assert transport.config["services"]["backend"]["command"] == command()
    assert admit_configuration(transport) == DIGEST
    inventory(transport)


@pytest.mark.parametrize(("old", "new"), [
    ("&& exec gunicorn", "&& exec exec gunicorn"),
    ("python manage.py", "exec python manage.py"),
    ("&& exec gunicorn", "&& exec  gunicorn"),
    ("&& exec gunicorn", "&&  exec gunicorn"),
    ("&& exec gunicorn", "; exec gunicorn"),
    ("&& exec gunicorn", "|| exec gunicorn"),
    ("python manage.py collectstatic --noinput && ", ""),
    ("collectstatic --noinput", "collectstatic"),
    ("config.wsgi:application", "configXwsgi:application"),
    ("config.wsgi:application", "other.wsgi:application"),
    ("--bind 0.0.0.0:8000", "--bind 127.0.0.1:8000"),
    ("--bind 0.0.0.0:8000", "--bind 0.0.0.0:8001"),
    ("--graceful-timeout 30", "--graceful-timeout 31"),
    ("--max-requests 1000", "--max-requests 1001"),
    ("--max-requests-jitter 100", "--max-requests-jitter 101"),
    ("--access-logfile -", "--access-logfile /tmp/access"),
    ("--error-logfile -", ""),
    ("--error-logfile -", "--error-logfile - --preload"),
    ("--workers 3 --timeout 60", "--timeout 60 --workers 3"),
    ("--error-logfile -", "--error-logfile - "),
    ("&& exec gunicorn", "&&\nexec gunicorn"),
])
@pytest.mark.parametrize("use_exec", [False, True], ids=["legacy-base", "exec-base"])
def test_shell_near_misses_refuse_real_admission(transport, old, new, use_exec):
    argv = command(use_exec=use_exec)
    if not use_exec:
        old = old.replace("&& exec gunicorn", "&& gunicorn")
    assert old in argv[4]  # Prevent a typo in a negative from becoming a no-op.
    argv[4] = argv[4].replace(old, new, 1)
    transport.config["services"]["backend"]["command"] = argv
    with pytest.raises(RestoreHostError, match="Custom backend commands"):
        admit_configuration(transport)


@pytest.mark.parametrize("field", ["workers", "timeout"])
@pytest.mark.parametrize("value", ["0", "-1", "+1", "01", "1.5", "abc", "1;true", ""])
@pytest.mark.parametrize("use_exec", [False, True])
def test_non_positive_or_non_decimal_limits_refuse_real_admission(transport, field, value, use_exec):
    transport.config["services"]["backend"]["command"] = command(use_exec=use_exec, **{field: value})
    with pytest.raises(RestoreHostError, match="Custom backend commands"):
        admit_configuration(transport)


@pytest.mark.parametrize("fault", ["role", "shell", "switch", "extra-argument", "direct"])
def test_wrong_role_or_argv_refuses_real_admission(transport, fault):
    argv = command()
    if fault == "role":
        argv[1] = "worker"  # Still a discovered writer; reaches the real role guard.
    elif fault == "shell":
        argv[2] = "bash"
    elif fault == "switch":
        argv[3] = "-lc"
    elif fault == "extra-argument":
        argv.append("extra")
    else:
        argv = ["--role", "backend", "gunicorn", "config.wsgi:application"]
    transport.config["services"]["backend"]["command"] = argv
    with pytest.raises(RestoreHostError, match="role command|Custom backend commands"):
        admit_configuration(transport)
