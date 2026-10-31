"""Run the actual standalone Node stamp CLI without npm, jsdom or network."""

import json
import os
import shutil
import subprocess
import tomllib

import pytest

from tests.deployment_verification_fakes import OTHER_SHA, ROOT, SENTINEL, SHA


pytestmark = pytest.mark.skipif(not (ROOT / "install.sh").exists(), reason="requires host checkout")


@pytest.fixture
def stamp(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("standalone stamp CLI requires Node (parent also runs under Node 20)")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    script = scripts / "write-build-revision.mjs"
    shutil.copyfile(ROOT / "frontend/scripts/write-build-revision.mjs", script)
    dist = tmp_path / "dist"
    dist.mkdir()
    unrelated_cwd = tmp_path / "other-working-directory"
    unrelated_cwd.mkdir()
    target = dist / "deployment.json"

    def run(values, existing=None):
        if existing is not None:
            target.write_text(existing)
        env = {"PATH": os.defpath, "HOME": str(tmp_path), "SENSITIVE_TOKEN": SENTINEL, **values}
        result = subprocess.run([node, str(script)], cwd=unrelated_cwd, env=env,
                                capture_output=True, text=True, timeout=10)
        assert SENTINEL not in result.stdout + result.stderr
        assert not (unrelated_cwd / "dist").exists()
        return result, target

    return run


@pytest.mark.parametrize(("values", "revision"), [
    ({"COMMIT_REF": SHA}, SHA),
    ({"SPACEWORKS_BUILD_REVISION": SHA}, SHA),
    ({"COMMIT_REF": SHA, "SPACEWORKS_BUILD_REVISION": SHA}, SHA),
    ({}, None),
])
def test_cli_writes_only_revision_metadata_relative_to_its_script(stamp, values, revision):
    result, target = stamp(values)
    assert result.returncode == 0, result.stderr
    assert target.read_text() == json.dumps({"revision": revision}, separators=(",", ":")) + "\n"
    assert json.loads(target.read_text()) == {"revision": revision}
    assert result.stdout == "Wrote frontend deployment metadata.\n"
    assert result.stderr == ""
    assert list(target.parent.iterdir()) == [target]


@pytest.mark.parametrize("key", ["COMMIT_REF", "SPACEWORKS_BUILD_REVISION"])
@pytest.mark.parametrize("bad", ["", SHA.upper(), SHA + "\n", SHA[:-1], "g" * 40, " " + SHA, SENTINEL])
def test_each_supplied_revision_must_be_valid_and_never_creates_a_stamp(stamp, key, bad):
    result, target = stamp({key: bad})
    assert result.returncode != 0
    assert not target.exists()
    assert result.stdout == ""
    assert result.stderr == "Could not write deployment metadata: check revision configuration and build output.\n"


@pytest.mark.parametrize("values", [
    {"COMMIT_REF": SHA, "SPACEWORKS_BUILD_REVISION": OTHER_SHA},
    {"COMMIT_REF": "", "SPACEWORKS_BUILD_REVISION": SHA},
    {"COMMIT_REF": SHA, "SPACEWORKS_BUILD_REVISION": ""},
    {"COMMIT_REF": SENTINEL, "SPACEWORKS_BUILD_REVISION": SHA},
])
def test_authoritative_netlify_revision_cannot_be_overridden_or_invalid_input_ignored(stamp, values):
    result, target = stamp(values)
    assert result.returncode != 0 and not target.exists()


def test_invalid_configuration_never_overwrites_existing_metadata(stamp):
    existing = json.dumps({"revision": OTHER_SHA})
    result, target = stamp({"COMMIT_REF": SHA, "SPACEWORKS_BUILD_REVISION": OTHER_SHA}, existing=existing)
    assert result.returncode != 0
    assert target.read_text() == existing


def test_package_build_stamps_only_after_successful_vite_and_netlify_only_disables_metadata_cache():
    package = json.loads((ROOT / "frontend/package.json").read_text())
    assert package["scripts"]["build"].split(" && ") == [
        "tsc -b", "vite build", "node scripts/write-build-revision.mjs",
    ]
    netlify = tomllib.loads((ROOT / "netlify.toml").read_text())
    assert netlify["build"]["base"] == "frontend"
    assert netlify["build"]["command"] == "npm run build"
    assert netlify["build"]["publish"] == "dist"
    assert netlify["headers"] == [{"for": "/deployment.json", "values": {"Cache-Control": "no-store"}}]
    assert netlify["redirects"] == [{"from": "/*", "to": "/index.html", "status": 200}]
