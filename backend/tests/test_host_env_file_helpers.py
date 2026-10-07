"""Host env helpers must treat deployment settings as data, never shell programs."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    not (ROOT / "install.sh").exists(),
    reason="host-only: the repository root is not in the backend image",
)


def _bash(script, *arguments, cwd=None):
    # Environment transport preserves quotes and newlines through MSYS's argv parser.
    values = {f"ENV_ARG_{index}": str(value) for index, value in enumerate(arguments)}
    positional = " ".join(f'"$ENV_ARG_{index}"' for index in range(len(arguments)))
    return subprocess.run(
        [shutil.which("bash") or "bash", "-c",
         'source "$ENV_HELPER"; set -- ' + positional + "; " + script, "env-test"],
        env={**os.environ, "BASH_ENV": "", **values,
             "ENV_HELPER": (ROOT / "scripts/env-file.sh").as_posix()},
        cwd=cwd,
        capture_output=True, text=True, timeout=10,
    )


@pytest.mark.parametrize(
    ("contents", "expected"),
    [
        ("SETTING=plain\n", "plain\n"),
        ('SETTING="Working on a project"\n', "Working on a project\n"),
        ("SETTING='*/5 * * * *'\n", "*/5 * * * *\n"),
        ("OTHER=value\n", ""),
        ("SETTING=first\nSETTING=second\n", "first\n"),
        ("SETTING=crlf\r\n", "crlf\n"),
        ("SETTING=unterminated", "unterminated\n"),
        ("SETTING=$(touch sentinel)\n", "$(touch sentinel)\n"),
        ("SETTING=latest # rolling release\n", "latest\n"),
        ('SETTING="keep # this" # comment\n', "keep # this\n"),
        ("SETTING=#literal\n", "#literal\n"),
        ("SETTING= # only a comment\n", "\n"),
        ("  export SETTING=exported  \n", "exported\n"),
        ("SETTING=stable # release # retained\n", "stable\n"),
        ("SETTING=a#b # c\n", "a#b\n"),
    ],
    ids=["unquoted", "double-quoted", "single-quoted", "absent-key",
         "first-match", "crlf", "no-final-newline", "literal-shell-text",
         "inline-comment", "quoted-then-comment", "hash-without-space",
         "comment-only", "export-prefix", "first-comment-delimiter",
         "literal-hash-then-comment"],
)
def test_env_file_get_reads_literal_first_value(tmp_path, contents, expected):
    """Compose-style quoting and CRLF must work without executing env-file contents."""
    dotenv = tmp_path / ".env"
    dotenv.write_bytes(contents.encode())
    result = _bash('env_file_get "$1" SETTING', dotenv.as_posix(), cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == expected
    assert not (tmp_path / "sentinel").exists()


def test_env_file_get_missing_file_is_empty(tmp_path):
    """A fresh install has no .env yet and must still be able to use defaults."""
    result = _bash('env_file_get "$1" SETTING', (tmp_path / "missing").as_posix())
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize(
    "value",
    ["$HOME", "a#b", "a'b", 'a"b', "a\\b", "a`b", "a\nb", "a\rb",
     " leading", "trailing ", "\tleading", "trailing\t", ""],
)
def test_env_value_refuses_ambiguous_or_executable_text(value):
    """Persisted values cannot inject interpolation, comments, quoting, or new records."""
    assert _bash('env_value_is_safe "$1"', value).returncode != 0


@pytest.mark.parametrize("value", ["Working on a project", "*/5 * * * *"])
def test_env_value_allows_internal_spaces(value):
    """Roster purposes and cron schedules need spaces inside a single literal value."""
    result = _bash('env_value_is_safe "$1"', value)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("original", [None, "OTHER=keep\n", "OTHER=keep"])
def test_append_is_idempotent_and_preserves_record_boundaries(tmp_path, original):
    """Rerunning setup must preserve settings and avoid joining two .env assignments."""
    dotenv = tmp_path / ".env"
    if original is not None:
        dotenv.write_bytes(original.encode())
    result = _bash(
        'env_file_append_if_absent "$1" SETTING "$2" && '
        'env_file_append_if_absent "$1" SETTING replacement',
        dotenv.as_posix(), "Working on a project",
    )
    assert result.returncode == 0, result.stderr
    prefix = "" if original is None else original.rstrip("\n") + "\n"
    assert dotenv.read_bytes() == (prefix + "SETTING=Working on a project\n").encode()


@pytest.mark.parametrize("line", ["export SETTING=kept\n", "  SETTING=kept\n", "  export SETTING=kept  \n"])
def test_append_treats_exported_and_indented_keys_as_present(tmp_path, line):
    """host_topology_record normalises these forms and rejects a repeated key."""
    dotenv = tmp_path / ".env"
    dotenv.write_bytes(line.encode())
    result = _bash('env_file_append_if_absent "$1" SETTING replacement', dotenv.as_posix())
    assert result.returncode == 0, result.stderr
    assert dotenv.read_bytes() == line.encode()


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize(("key", "value"), [("SETTING", "$unsafe"), ("lowercase", "safe")])
def test_rejected_append_does_not_write(tmp_path, existing, key, value):
    """Validation must happen before file creation or repair of a missing final newline."""
    dotenv = tmp_path / ".env"
    if existing:
        dotenv.write_bytes(b"OTHER=keep")
    result = _bash('env_file_append_if_absent "$1" "$2" "$3"',
                   dotenv.as_posix(), key, value)
    assert result.returncode != 0
    if existing:
        assert dotenv.read_bytes() == b"OTHER=keep"
    else:
        assert not dotenv.exists()


@pytest.mark.parametrize(
    ("schedule", "expected"),
    [
        ("0  3 * * 0", "0 3 * * 0"),
        (" \t0\t3 * * 0 ", "0 3 * * 0"),
        ("0 0 1 1 0", "0 0 1 1 0"),
        ("59 23 31 12 7", "59 23 31 12 7"),
        ("*/5 * * * *", "*/5 * * * *"),
        ("0-59 0-23 1-31 1-12 0-7", "0-59 0-23 1-31 1-12 0-7"),
        ("1-9/2 */3 1,15 1,12 0,7", "1-9/2 */3 1,15 1,12 0,7"),
        ("5/2 3 1 1 0", "5/2 3 1 1 0"),
        ("00 03 01 01 07", "00 03 01 01 07"),
    ],
)
def test_cron_accepts_numeric_grammar_and_canonicalises_spacing(schedule, expected):
    """Validated schedules must remain usable by cron after whitespace normalisation."""
    result = _bash('validate_cron_schedule "$1"', schedule)
    assert result.returncode == 0, result.stderr
    assert result.stdout == expected + "\n"


@pytest.mark.parametrize(
    "schedule",
    [
        "", "* * * *", "* * * * * *", "60 * * * *", "-1 * * * *",
        "* 24 * * *", "* -1 * * *", "* * 0 * *", "* * 32 * *",
        "* * * 0 *", "* * * 13 *", "* * * * -1", "* * * * 8",
        "0-60 * * * *", "* 0-24 * * *", "* * 1-32 * *",
        "* * * 1-13 *", "* * * * 0-8", "5-1 * * * *",
        "*/0 * * * *", "1-9/0 * * * *", "*/-1 * * * *", "*//2 * * * *",
        "1,60 * * * *", ",1 * * * *", "1, * * * *", "1,,2 * * * *",
        "0 3 * * SUN", "@weekly", "0 3 * * 0%", "0 3 * * 0\n* * * * * evil",
        "0 3 * * 0\r", "* * * * *; rm -rf /", "999999999999999999 * * * *",
    ],
)
def test_cron_refuses_invalid_bounds_syntax_and_record_injection(schedule):
    """Reject bad fields and cron's percent/newline syntax before a job can be installed."""
    result = _bash('validate_cron_schedule "$1"', schedule)
    assert result.returncode != 0, result.stdout
    assert result.stdout == ""
