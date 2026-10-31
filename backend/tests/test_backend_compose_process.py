"""Permanent command contracts: actual YAML, no Compose CLI or daemon needed."""

import json
from pathlib import Path
import shlex

import pytest
import yaml


ROOT = Path("/workspace") if Path("/workspace/docker-compose.yml").is_file() else Path(__file__).resolve().parents[2]
PROFILES = ("docker-compose.yml", "docker-compose.prod.yml", "docker-compose.cloud.yml")
COLLECTSTATIC = ["python", "manage.py", "collectstatic", "--noinput"]
GUNICORN = ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
PRODUCTION_FLAGS = [
    "--workers", "3", "--timeout", "60", "--graceful-timeout", "30",
    "--max-requests", "1000", "--max-requests-jitter", "100",
    "--access-logfile", "-", "--error-logfile", "-",
]


class ComposeLoader(yaml.SafeLoader):
    """Read dev's Compose sequence tags without implementing Compose merging."""


ComposeLoader.add_constructor("!override", lambda loader, node: loader.construct_sequence(node))
ComposeLoader.add_constructor("!reset", lambda loader, node: loader.construct_scalar(node))


def services(name):
    return yaml.load((ROOT / name).read_text(encoding="utf-8"), Loader=ComposeLoader)["services"]


def backend_shell_tokens(command):
    if (not isinstance(command, list) or len(command) != 5
            or command[:4] != ["--role", "backend", "sh", "-c"]
            or not isinstance(command[4], str)):
        raise ValueError("Expected one backend role and one sh -c body")
    if "\n" in command[4] or "\r" in command[4]:
        raise ValueError("Shell body must stay on one line")
    lexer = shlex.shlex(command[4], posix=True, punctuation_chars=";&|")
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


@pytest.mark.parametrize("profile", PROFILES)
def test_backend_collectstatic_conditionally_execs_exact_gunicorn_argv(profile):
    command = services(profile)["backend"]["command"]
    flags = [] if profile == "docker-compose.yml" else PRODUCTION_FLAGS
    raw_flags = [
        "${GUNICORN_WORKERS:-3}" if value == "3" else
        "${GUNICORN_TIMEOUT:-60}" if value == "60" else value
        for value in flags
    ]
    expected = COLLECTSTATIC + ["&&", "exec"] + GUNICORN
    # Exact token equality detects a lost && boundary, stray command, or moved flag.
    assert backend_shell_tokens(command) == expected + raw_flags
    decoded = command.copy()
    decoded[4] = decoded[4].replace("${GUNICORN_WORKERS:-3}", "3").replace("${GUNICORN_TIMEOUT:-60}", "60")
    assert backend_shell_tokens(decoded) == expected + flags


@pytest.mark.parametrize("profile", PROFILES)
def test_candidate_backend_keeps_direct_gunicorn_without_collectstatic(profile):
    flags = [] if profile == "docker-compose.yml" else [
        "--workers", "1", "--access-logfile", "-", "--error-logfile", "-",
    ]
    assert services(profile)["candidate-backend"]["command"] == ["--role", "backend"] + GUNICORN + flags


def test_image_default_keeps_direct_gunicorn():
    declarations = [line[4:] for line in (ROOT / "backend/Dockerfile").read_text().splitlines() if line.startswith("CMD ")]
    assert len(declarations) == 1
    assert json.loads(declarations[0]) == ["--role", "backend"] + GUNICORN


@pytest.mark.parametrize("role", ["backend", "candidate-backend"])
def test_development_keeps_direct_runserver(role):
    assert services("docker-compose.dev.yml")[role]["command"] == [
        "--role", "backend", "python", "manage.py", "runserver", "0.0.0.0:8000",
    ]


@pytest.mark.parametrize("command", [
    None, "sh -c gunicorn", [], ["--role", "backend", "sh", "-c"],
    ["--role", "worker", "sh", "-c", "gunicorn"],
    ["--role", "backend", "bash", "-c", "gunicorn"],
    ["--role", "backend", "sh", "-c", ["gunicorn"]],
    ["--role", "backend", "sh", "-c", "gunicorn", "extra"],
    ["--role", "backend", "sh", "-c", "gunicorn\n--bind localhost"],
    ["--role", "backend", "sh", "-c", "gunicorn 'unclosed"],
])
def test_shell_decoder_refuses_malformed_role_or_shell_argv(command):
    with pytest.raises(ValueError):
        backend_shell_tokens(command)
