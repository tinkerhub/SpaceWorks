"""Retained, global and import-journal references fence ordinary cleanup and credit."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.backup.models import BackupArchive
from apps.evidence.models import EvidencePhoto
from apps.tenant_migration.models import TenantImportJob, TenantImportObject
from tests.document_safety.helpers import lab, usage
from tests.document_quota.helpers import delete, legacy_row, releases, upload

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("kind", ["receipt", "asset"])
@pytest.mark.parametrize("holder", ["foreign-evidence", "global-backup", "import-target", "import-source", "import-staging"])
def test_actual_retained_reference_blocks_provider_cleanup_and_credit(kind, holder, monkeypatch, settings):
    case = lab(monkeypatch, settings, kind)
    row, _, body = upload(case)
    key = row.object_key
    if holder == "foreign-evidence":
        survivor = EvidencePhoto.objects.create(
            makerspace=case.other, uploaded_by=case.actor, evidence_type="issue", object_key=key,
        )
    elif holder == "global-backup":
        survivor = BackupArchive.objects.create(
            scope=BackupArchive.Scope.DEPLOYMENT, makerspace=None, object_key=key,
        )
    else:
        job = TenantImportJob.objects.create(
            target_makerspace=None, source_archive_digest="a" * 64,
            expires_at=timezone.now() + timedelta(days=1),
        )
        fields = dict(source_key="source/other", staging_key="imports/other",
                      target_key="target/other", bucket_kind="private", size=len(body), sha256="b" * 64)
        fields[{"import-target": "target_key", "import-source": "source_key",
                "import-staging": "staging_key"}[holder]] = key
        survivor = TenantImportObject.objects.create(job=job, **fields)
    calls = list(case.store.calls)
    assert delete(case, row).status_code == 204
    assert not case.model.objects.filter(pk=row.pk).exists()
    assert type(survivor).objects.filter(pk=survivor.pk).exists()
    assert case.store.calls == calls and case.store.objects[key][0] == body
    assert usage(case) == len(body) and not releases(case).exists()


@pytest.mark.parametrize("kind", ["receipt", "asset"])
def test_reference_created_during_provider_delete_refuses_accounting_settlement(kind, monkeypatch, settings):
    case = lab(monkeypatch, settings, kind)
    row, _, body = upload(case)
    replacements = []
    def after_preflight(_):
        replacements.append(legacy_row(case, key=row.object_key))
    case.store.before_delete = after_preflight
    response = delete(case, row)
    assert response.status_code == 503
    assert response.data == {
        "detail": "Evidence storage is unavailable.", "code": "evidence_storage_unavailable",
    }
    assert len(replacements) == 1 and case.model.objects.filter(pk=replacements[0].pk).exists()
    assert not case.store.versions.get(row.object_key)
    assert usage(case) == len(body) and not releases(case).exists()
