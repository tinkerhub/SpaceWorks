"""Certificate fixtures that retain real workflow, audit and quota behavior."""

import hashlib
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.accounts.models import User
from apps.events import certificate_cleanup, certificate_storage, services_certificates as certificates
from apps.events.models import EventRegistration
from apps.events.services_feedback import submit_identified_feedback
from tests.events.test_postevent_feedback import ended_event, opened_survey, registration
from tests.member_submission import active_member_client


def certificate_case(slug):
    event = ended_event(slug)
    space = event.makerspace
    space.resource_limit_overrides = {"storage": 10000}
    space.save(update_fields=["resource_limit_overrides"])
    opened_survey(event, certificate=True)
    member, _client = active_member_client(space, f"{slug}-member")
    row = registration(event, member, EventRegistration.Status.ATTENDED)
    response, certificate = submit_identified_feedback(
        event, actor=member, registration=row, email=member.email, answers={"rating": 5},
    )
    actor = User.objects.create_user(username=f"{slug}-staff")
    return SimpleNamespace(
        event=event, space=space, actor=actor, registration=row,
        response=response, certificate=certificate,
    )


def move_to(certificate, status):
    if status in {"rendering", "failed"}:
        certificates._claim_render(certificate.pk)
        if status == "failed":
            certificates._fail_render(certificate.pk)
    elif status == "active":
        certificates.render_certificate(certificate)
    elif status != "pending":
        raise AssertionError(f"Unsupported fixture state: {status}")
    certificate.refresh_from_db()
    assert certificate.status == status
    return certificate


@pytest.fixture
def certificate_io(monkeypatch, settings):
    settings.PLATFORM_DOMAIN_SUFFIX = ".space-works.tech"
    objects, operations = {}, []

    def store(key, payload):
        objects[key] = payload
        operations.append(("upload", key))
        return len(payload), hashlib.sha256(payload).hexdigest()

    def delete(_client, *, bucket, key):
        objects.pop(key, None)
        operations.append(("delete", key))

    render = Mock(return_value=b"%PDF-1.4 regression certificate")
    upload = Mock(side_effect=store)
    download = Mock(return_value="https://storage.example.test/private-certificate")
    cleanup = Mock(side_effect=delete)
    monkeypatch.setattr(certificates, "render_certificate_pdf", render)
    monkeypatch.setattr(certificates, "store_immutable_pdf", upload)
    monkeypatch.setattr(certificates, "presigned_download", download)
    monkeypatch.setattr(certificate_storage, "_client", Mock(return_value=object()))
    monkeypatch.setattr(certificate_cleanup, "delete_all_versions", cleanup)
    return SimpleNamespace(
        render=render, upload=upload, download=download, cleanup=cleanup,
        objects=objects, operations=operations, store=store,
    )
