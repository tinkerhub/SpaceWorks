"""The real reconciler counts series images and durable issued certificate bytes."""

from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError
from django.core.management import call_command

from apps.events import certificate_storage, services_certificates as certificates
from apps.events.models import EventRegistration, EventSeries
from apps.events.services_feedback import submit_identified_feedback
from apps.inventory import public_image_storage
from apps.maintenance import storage as maintenance_storage
from apps.makerspaces.models import Makerspace
from tests.events.certificate_recovery_helpers import certificate_case, certificate_io, move_to
from tests.events.test_event_series import recurrence_fixture
from tests.events.test_postevent_feedback import ended_event, registration
from tests.member_submission import active_member_client
from tests.return_helpers import make_product, make_space
from tests.test_storage_reconciler_gaps import make_document


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def storage_heads(monkeypatch):
    sizes, failures = {}, {}

    def head_object(*, Bucket, Key):
        if Key in failures:
            raise failures[Key]
        if Key not in sizes:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "HeadObject")
        return {"ContentLength": sizes[Key]}

    client = Mock(spec=["head_object"])
    client.head_object.side_effect = head_object
    monkeypatch.setattr(public_image_storage, "_client", lambda: client)
    monkeypatch.setattr(maintenance_storage, "_client", lambda: client)
    return SimpleNamespace(client=client, sizes=sizes, failures=failures)


def series_image(space, key):
    return EventSeries.objects.create(
        makerspace=space, title="Series cover", image_key=key,
        **vars(recurrence_fixture()),
    )


def recompute(space):
    output = StringIO()
    call_command("recompute_storage", space.slug, stdout=output)
    space.refresh_from_db()
    return output.getvalue()


def additional_pending(case, suffix):
    member, _client = active_member_client(case.space, f"artifact-{suffix}")
    row = registration(case.event, member, EventRegistration.Status.ATTENDED)
    _response, certificate = submit_identified_feedback(
        case.event, actor=member, registration=row, email=member.email,
        answers={"rating": 5},
    )
    return certificate


def test_recompute_counts_series_cover_without_any_occurrences(storage_heads):
    space = make_space("recompute-series-only")
    series = series_image(space, "event-series/standalone.webp")
    assert not series.occurrences.exists()
    storage_heads.sizes[series.image_key] = 73

    output = recompute(space)

    assert space.storage_bytes_used == 73
    assert "total=73 bytes" in output
    assert [call.kwargs["Key"] for call in storage_heads.client.head_object.call_args_list] == [series.image_key]


def test_recompute_deduplicates_series_event_and_other_public_images(storage_heads):
    event = ended_event("recompute-shared-cover")
    space = event.makerspace
    shared = "public-images/shared-cover.webp"
    series = series_image(space, shared)
    event.series = series
    event.series_occurrence_key = "shared-cover-occurrence"
    event.series_revision = series.revision
    event.image_key = shared
    event.save(update_fields=["series", "series_occurrence_key", "series_revision", "image_key"])
    make_product(space, image_key=shared)
    space.logo_key = shared
    space.cover_image_key = "public-images/distinct-cover.webp"
    space.save(update_fields=["logo_key", "cover_image_key"])
    document = make_document(space, size=17, index=0)
    foreign = make_space("recompute-foreign-series")
    foreign_series = series_image(foreign, "event-series/foreign.webp")
    storage_heads.sizes.update({shared: 73, space.cover_image_key: 29, foreign_series.image_key: 999})
    # A missing legacy maintenance object retains its recorded-size fallback.
    expected = 73 + 29 + document.size_bytes

    for _ in range(2):
        storage_heads.client.head_object.reset_mock()
        recompute(space)
        assert space.storage_bytes_used == expected
        requested = [call.kwargs["Key"] for call in storage_heads.client.head_object.call_args_list]
        assert sorted(requested) == sorted([shared, space.cover_image_key, document.object_key])
        assert requested.count(shared) == 1
    foreign.refresh_from_db()
    assert foreign.storage_bytes_used == 0


def test_recompute_counts_only_issued_certificate_metadata_in_selected_tenant(
    storage_heads, certificate_io, django_capture_on_commit_callbacks,
):
    case = certificate_case("recompute-issued-certificates")
    issued = move_to(case.certificate, "active")
    with django_capture_on_commit_callbacks(execute=True):
        certificates.revoke(issued, actor=case.actor, reason="staff_revoked")
    issued.refresh_from_db()
    replacement = certificates.reissue(case.registration, actor=case.actor)
    active = move_to(replacement, "active")
    for status in ("pending", "failed", "rendering", "revoked"):
        unissued = additional_pending(case, status)
        if status == "revoked":
            with django_capture_on_commit_callbacks(execute=True):
                certificates.revoke(unissued, actor=case.actor, reason="staff_revoked")
        else:
            move_to(unissued, status)
        unissued.refresh_from_db()
        assert unissued.status == status
        assert unissued.size_bytes is None and unissued.rendered_at is None
    foreign = certificate_case("recompute-foreign-certificate")
    foreign_certificate = move_to(foreign.certificate, "active")
    foreign.space.refresh_from_db()
    foreign_charge = foreign.space.storage_bytes_used
    assert foreign_charge == foreign_certificate.size_bytes > 0
    snapshot = [(row.pk, row.size_bytes, row.sha256, row.rendered_at) for row in (issued, active)]
    assert all(size == len(certificate_io.render.return_value) and digest and rendered for _, size, digest, rendered in snapshot)
    Makerspace.objects.filter(pk=case.space.pk).update(storage_bytes_used=9000)
    # The never-issued revoke legitimately contacted cleanup storage during setup.
    # Reconciliation itself must use issued metadata without a certificate HEAD.
    certificate_storage._client.reset_mock()

    for _ in range(2):
        recompute(case.space)
        assert case.space.storage_bytes_used == issued.size_bytes + active.size_bytes
    foreign.space.refresh_from_db()
    assert foreign.space.storage_bytes_used == foreign_charge
    for row, before in zip((issued, active), snapshot):
        row.refresh_from_db()
        assert (row.pk, row.size_bytes, row.sha256, row.rendered_at) == before
    storage_heads.client.head_object.assert_not_called()
    certificate_storage._client.assert_not_called()


def test_recompute_retains_active_certificate_charge_after_revocation(
    storage_heads, certificate_io, django_capture_on_commit_callbacks,
):
    case = certificate_case("recompute-revocation-charge")
    certificate = move_to(case.certificate, "active")
    size = certificate.size_bytes

    recompute(case.space)
    assert case.space.storage_bytes_used == size > 0
    with django_capture_on_commit_callbacks(execute=True):
        certificates.revoke(certificate, actor=case.actor, reason="staff_revoked")
    recompute(case.space)

    certificate.refresh_from_db()
    assert certificate.status == "revoked"
    assert certificate.size_bytes == size
    assert case.space.storage_bytes_used == size
    assert certificate_io.objects[certificate.object_key]
    storage_heads.client.head_object.assert_not_called()
    certificate_storage._client.assert_not_called()


def test_series_image_head_failure_preserves_previous_usage_with_storage_warning(storage_heads):
    space = make_space("recompute-series-read-failure")
    series = series_image(space, "event-series/unreadable.webp")
    Makerspace.objects.filter(pk=space.pk).update(storage_bytes_used=321)
    storage_heads.failures[series.image_key] = ClientError({
        "Error": {"Code": "AccessDenied", "Message": "private-provider-secret"},
        "ResponseMetadata": {"HTTPStatusCode": 403},
    }, "HeadObject")

    output = recompute(space)

    assert space.storage_bytes_used == 321
    assert f"usage left unchanged due to storage read error for {series.image_key}." in output
    assert "total=" not in output
    assert "private-provider-secret" not in output


def test_missing_series_image_uses_existing_zero_size_policy(storage_heads):
    space = make_space("recompute-series-missing")
    series = series_image(space, "event-series/missing.webp")
    document = make_document(space, size=19, index=0)
    Makerspace.objects.filter(pk=space.pk).update(storage_bytes_used=321)

    output = recompute(space)

    assert space.storage_bytes_used == document.size_bytes
    assert "total=19 bytes" in output
    assert "left unchanged" not in output
    assert series.image_key in {call.kwargs["Key"] for call in storage_heads.client.head_object.call_args_list}
