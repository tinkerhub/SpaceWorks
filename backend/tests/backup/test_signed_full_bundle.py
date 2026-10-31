"""Use real tar files and production validators for all full payload classes."""

import json
import os
import tarfile

import pytest

from apps.backup.errors import BackupBuildError
from apps.backup.full_bundle import verify_full_bundle, verify_full_root
from apps.backup.import_preflight import ImportPreflightError
from tests.backup.full_backup_fixture_helpers import make_full_fixture, sign_manifest


PAYLOADS = ["database.dump", "keys/env.json", "objects/private/evidence/issue.jpg",
            "objects/public_image/inventory/tool.png"]


def verify(fixture):
    verify_full_bundle(fixture.bundle, fixture.manifest, fixture.manifest_file, fixture.secrets_file)


def test_complete_real_tar_and_extracted_root_are_admitted(tmp_path):
    fixture = make_full_fixture(tmp_path)
    verify(fixture)
    verify_full_root(fixture.root, fixture.manifest)


@pytest.mark.parametrize("name", PAYLOADS)
@pytest.mark.parametrize("mutation", ["tamper", "missing"])
def test_tar_every_payload_class_tamper_or_omission_refuses(tmp_path, name, mutation):
    fixture = make_full_fixture(tmp_path)
    if mutation == "tamper":
        fixture.write_tar(replacements={name: b"changed payload"})
    else:
        fixture.write_tar(omit={name})
    with pytest.raises(BackupBuildError, match="ledger"):
        verify(fixture)


@pytest.mark.parametrize("name", [
    "unexpected", "../outside", "/absolute", "objects/private/../escape",
    "objects//private/alias", "objects/private/./alias", "objects\\private\\alias",
    "Database.dump", "./database.dump", "database.dump",
])
def test_tar_extra_alias_duplicate_traversal_and_case_refuse(tmp_path, name):
    fixture = make_full_fixture(tmp_path)
    member = tarfile.TarInfo(name)
    member.size = 1
    fixture.write_tar(extra=[(member, b"x")])
    with pytest.raises(BackupBuildError):
        verify(fixture)


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE,
                                   tarfile.CHRTYPE, tarfile.BLKTYPE, tarfile.DIRTYPE])
def test_tar_links_special_files_and_undeclared_directories_refuse(tmp_path, kind):
    fixture = make_full_fixture(tmp_path)
    member = tarfile.TarInfo("injected")
    member.type = kind
    member.linkname = "database.dump"
    fixture.write_tar(extra=[(member, None)])
    with pytest.raises(BackupBuildError):
        verify(fixture)


@pytest.mark.parametrize("name", [*PAYLOADS, "manifest.json"])
def test_extracted_bytes_changed_after_tar_validation_refuse(tmp_path, name):
    fixture = make_full_fixture(tmp_path)
    verify(fixture)
    (fixture.root / name).write_bytes(b"changed after validation")
    if name == "manifest.json":
        with pytest.raises(ImportPreflightError) as refused:
            verify_full_root(fixture.root, fixture.manifest)
        assert type(refused.value) is ImportPreflightError
        assert refused.value.reason == "component_policy"
    else:
        with pytest.raises(BackupBuildError):
            verify_full_root(fixture.root, fixture.manifest)
    if name in {"manifest.json", "keys/env.json"}:
        if name == "manifest.json":
            with pytest.raises(ImportPreflightError) as refused:
                verify(fixture)
            assert type(refused.value) is ImportPreflightError
            assert refused.value.reason == "component_policy"
        else:
            with pytest.raises(BackupBuildError):
                verify(fixture)


@pytest.mark.parametrize("kind", ["file", "directory", "symlink", "fifo"])
def test_extracted_unlisted_entries_and_links_refuse(tmp_path, kind):
    fixture = make_full_fixture(tmp_path)
    path = fixture.root / "extra"
    if kind == "file":
        path.write_bytes(b"unlisted")
    elif kind == "directory":
        path.mkdir()
    elif kind == "symlink":
        path.symlink_to(fixture.root / "database.dump")
    else:
        os.mkfifo(path)
    with pytest.raises(BackupBuildError):
        verify_full_root(fixture.root, fixture.manifest)


def test_same_json_different_continuity_bytes_refuse(tmp_path):
    fixture = make_full_fixture(tmp_path)
    fixture.secrets_file.write_text(json.dumps(fixture.secrets, indent=4))
    assert json.loads(fixture.secrets_file.read_bytes()) == fixture.secrets
    with pytest.raises(BackupBuildError):
        verify(fixture)
    with pytest.raises(BackupBuildError):
        verify_full_root(fixture.root, fixture.manifest)


def test_duplicate_continuity_json_keys_refuse_even_if_signed_bytes_agree(tmp_path):
    from tests.backup.full_backup_fixture_helpers import sha

    fixture = make_full_fixture(tmp_path)
    raw = fixture.members["keys/env.json"]
    raw = b'{"SECRET_KEY":"untrusted",' + raw[1:]
    fixture.members["keys/env.json"] = raw
    fact = next(item for item in fixture.manifest["contents"] if item["path"] == "keys/env.json")
    fact.update(size=len(raw), sha256=sha(raw))
    fixture.manifest = sign_manifest(fixture.manifest)
    fixture.write()
    with pytest.raises((BackupBuildError, RuntimeError)):
        verify(fixture)


def test_extracted_hardlinked_payload_refuses_even_when_bytes_match(tmp_path):
    fixture = make_full_fixture(tmp_path)
    external = tmp_path / "outside-dump"
    external.write_bytes(fixture.members["database.dump"])
    payload = fixture.root / "database.dump"
    payload.unlink()
    os.link(external, payload)
    with pytest.raises(BackupBuildError):
        verify_full_root(fixture.root, fixture.manifest)


def test_expired_evidence_is_a_signed_no_byte_tombstone(tmp_path):
    fixture = make_full_fixture(tmp_path)
    expired = dict(fixture.manifest["storage"]["objects"][0])
    expired.update(key="evidence/expired.jpg", retention_state="expired", size=0, sha256="",
                   object_expired_at="2026-10-28T00:00:00+00:00", expired_size_bytes=123)
    fixture.manifest["storage"]["objects"].append(expired)
    fixture.manifest = sign_manifest(fixture.manifest)
    fixture.write()
    verify(fixture)
    member = tarfile.TarInfo("objects/private/evidence/expired.jpg")
    member.size = 1
    fixture.write_tar(extra=[(member, b"x")])
    with pytest.raises(BackupBuildError):
        verify(fixture)
