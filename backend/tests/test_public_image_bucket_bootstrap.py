"""Run bucket initialization against a local fake mc, with no provider access."""

import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from textwrap import dedent
from types import SimpleNamespace

import pytest
import yaml


MOUNTED_REPO_ROOT = Path("/workspace")
REPO_ROOT = (
    MOUNTED_REPO_ROOT
    if (MOUNTED_REPO_ROOT / "backend" / "config" / "settings.py").is_file()
    else Path(__file__).resolve().parents[2]
)
SCRIPT = REPO_ROOT / "deploy" / "init-object-buckets.sh"
COMPOSE_FILES = ("docker-compose.yml", "docker-compose.prod.yml")
pytestmark = pytest.mark.skipif(
    not SCRIPT.is_file() or any(not (REPO_ROOT / name).is_file() for name in COMPOSE_FILES),
    reason="Full repository files require a host checkout or /workspace mount.",
)
PRIVATE = "tenant-evidence"
PUBLIC = "tenant-gallery.v2"


@pytest.fixture
def bootstrap(tmp_path):
    # The shell can find only our mc and the three local utilities it needs.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("mktemp", "cat", "rm"):
        executable = shutil.which(name)
        assert executable, f"Missing local shell utility: {name}"
        (bin_dir / name).symlink_to(executable)
    log = tmp_path / "mc.jsonl"
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"buckets": []}), encoding="utf-8")
    mc = bin_dir / "mc"
    mc.write_text(f"#!{sys.executable}\n" + dedent('''\
        import json
        import os
        from pathlib import Path
        import sys

        args = sys.argv[1:]
        record = {"argv": args}
        if args[:2] == ["anonymous", "set-json"]:
            record["policy"] = json.loads(Path(args[2]).read_text())
        with open(os.environ["FAKE_MC_LOG"], "a") as handle:
            handle.write(json.dumps(record) + "\\n")
        state_path = Path(os.environ["FAKE_MC_STATE"])
        state = json.loads(state_path.read_text())
        if args[:2] == ["alias", "set"]:
            assert args == ["alias", "set", "--", "local", "http://minio:9000",
                            "dummy-bootstrap-user", os.environ["FAKE_MC_EXPECTED_PASSWORD"]]
        elif args[:1] == ["mb"]:
            target = args[-1]
            if target in state["buckets"] and "--ignore-existing" not in args:
                sys.exit(1)
            if target not in state["buckets"]:
                state["buckets"].append(target)
                state_path.write_text(json.dumps(state))
        elif args[:2] == ["version", "enable"]:
            assert args[-1] in state["buckets"]
        elif args[:3] == ["anonymous", "set", "none"]:
            assert args[-1] in state["buckets"]
        elif args[:2] == ["anonymous", "set-json"]:
            assert args[-1] in state["buckets"]
            if os.environ["FAKE_MC_POLICY_FAIL"] == "1":
                sys.exit(23)
        else:
            raise AssertionError("Unexpected mc command: " + repr(args))
        '''), encoding="utf-8")
    mc.chmod(0o755)

    def run(*, private=PRIVATE, public=PUBLIC, policy_failure=False,
            password="dummy-bootstrap-password"):
        return subprocess.run(
            ["/bin/sh", str(SCRIPT)], cwd=tmp_path,
            env={
                "PATH": str(bin_dir), "TMPDIR": str(tmp_path),
                "MINIO_ROOT_USER": "dummy-bootstrap-user",
                "MINIO_ROOT_PASSWORD": password,
                "AWS_STORAGE_BUCKET_NAME": private, "PUBLIC_IMAGE_BUCKET": public,
                "FAKE_MC_LOG": str(log), "FAKE_MC_STATE": str(state),
                "FAKE_MC_POLICY_FAIL": "1" if policy_failure else "0",
                "FAKE_MC_EXPECTED_PASSWORD": password,
            },
            capture_output=True, text=True, timeout=10, check=False,
        )

    def calls():
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    return SimpleNamespace(run=run, calls=calls, state=state)


def assert_policy(policy):
    assert policy["Version"] == "2012-10-17"
    # Every final-key namespace works, including future ones; no anonymous listing.
    allow, deny = policy["Statement"]
    assert allow == {
        "Effect": "Allow", "Principal": {"AWS": ["*"]},
        "Action": ["s3:GetObject"], "Resource": [f"arn:aws:s3:::{PUBLIC}/*"],
    }
    # The deny overrides the broad read only for unsigned staging reads. A signed
    # uploader/finalizer retains access because its principal is not Anonymous.
    assert deny == {
        "Effect": "Deny", "Principal": {"AWS": ["*"]},
        "Action": ["s3:GetObject", "s3:GetObjectVersion"],
        "Resource": [f"arn:aws:s3:::{PUBLIC}/staging/*"],
        "Condition": {"StringEquals": {"aws:principaltype": ["Anonymous"]}},
    }


@pytest.mark.parametrize("existing", [False, True], ids=["fresh", "existing"])
def test_custom_bucket_setup_is_private_versioned_and_idempotent(bootstrap, existing):
    if existing:
        bootstrap.state.write_text(json.dumps({
            "buckets": [f"local/{PRIVATE}", f"local/{PUBLIC}"],
        }), encoding="utf-8")

    first = bootstrap.run()
    second = bootstrap.run()

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    calls = bootstrap.calls()
    assert len(calls) == 14
    for batch in (calls[:7], calls[7:]):
        assert [entry["argv"] for entry in batch[:6]] == [
            ["alias", "set", "--", "local", "http://minio:9000",
             "dummy-bootstrap-user", "dummy-bootstrap-password"],
            ["mb", "--ignore-existing", f"local/{PRIVATE}"],
            ["version", "enable", f"local/{PRIVATE}"],
            ["anonymous", "set", "none", f"local/{PRIVATE}"],
            ["mb", "--ignore-existing", f"local/{PUBLIC}"],
            ["version", "enable", f"local/{PUBLIC}"],
        ]
        assert batch[6]["argv"][:2] == ["anonymous", "set-json"]
        assert batch[6]["argv"][3:] == [f"local/{PUBLIC}"]
        assert_policy(batch[6]["policy"])
        assert not Path(batch[6]["argv"][2]).exists(), "Policy temporary file leaked"
    assert set(json.loads(bootstrap.state.read_text())["buckets"]) == {
        f"local/{PRIVATE}", f"local/{PUBLIC}",
    }


@pytest.mark.parametrize("password", [
    pytest.param("-dummy-bootstrap-password", id="single-hyphen"),
    pytest.param("--dummy-bootstrap-password", id="double-hyphen"),
])
def test_leading_hyphen_password_is_literal_and_not_logged(bootstrap, password):
    result = bootstrap.run(password=password)

    assert result.returncode == 0, result.stderr
    assert bootstrap.calls()[0]["argv"] == [
        "alias", "set", "--", "local", "http://minio:9000",
        "dummy-bootstrap-user", password,
    ]
    for output in (result.stdout, result.stderr):
        assert password not in output
        assert "dummy-bootstrap-user" not in output


def test_policy_failure_fails_bucket_bootstrap(bootstrap):
    result = bootstrap.run(policy_failure=True)

    assert result.returncode != 0
    calls = bootstrap.calls()
    assert len(calls) == 7
    assert calls[-1]["argv"][:2] == ["anonymous", "set-json"]
    assert_policy(calls[-1]["policy"])
    assert not Path(calls[-1]["argv"][2]).exists()


@pytest.mark.parametrize("private,public", [
    pytest.param("same-bucket", "same-bucket", id="equal-buckets"),
    pytest.param(PRIVATE, 'gallery"injection', id="json-quote"),
    pytest.param(PRIVATE, "gallery\\injection", id="json-backslash"),
    pytest.param(PRIVATE, "gallery\ninjection", id="json-newline"),
])
def test_invalid_bucket_configuration_is_rejected_before_mc(bootstrap, private, public):
    result = bootstrap.run(private=private, public=public)

    assert result.returncode != 0
    assert bootstrap.calls() == []


@pytest.mark.parametrize("name", COMPOSE_FILES)
def test_compose_bucket_bootstrap_uses_shared_script_and_custom_bucket_env(name):
    service = yaml.safe_load((REPO_ROOT / name).read_text(encoding="utf-8"))[
        "services"
    ]["createbuckets"]

    assert service["volumes"] == [
        "./deploy/init-object-buckets.sh:/usr/local/bin/init-object-buckets.sh:ro",
    ]
    entrypoint = service["entrypoint"]
    assert entrypoint.startswith("/bin/sh -c")
    argv = shlex.split(entrypoint)
    assert argv[:2] == ["/bin/sh", "-c"]
    assert shlex.split(argv[2]) == ["exec", "/bin/sh", "/usr/local/bin/init-object-buckets.sh"]
    env = service["environment"]
    assert env["AWS_STORAGE_BUCKET_NAME"] == "${AWS_STORAGE_BUCKET_NAME:-evidence}"
    assert env["PUBLIC_IMAGE_BUCKET"] == "${PUBLIC_IMAGE_BUCKET:-public-images}"
    if name == "docker-compose.prod.yml":
        assert env["MINIO_ROOT_USER"] == "${MINIO_ROOT_USER:?set MINIO_ROOT_USER}"
        assert env["MINIO_ROOT_PASSWORD"] == "${MINIO_ROOT_PASSWORD:?set MINIO_ROOT_PASSWORD}"
