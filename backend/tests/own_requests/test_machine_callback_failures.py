"""A failed callback lookup cannot turn an already committed reprint into HTTP 500."""

import logging

import pytest
from django.db import connection
from django.urls import reverse
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.integrations.models import EmailLog, NotificationDeliveryLog
from apps.machines.models import MachineServiceRequest
from apps.notifications.models import Notification
from tests.own_requests.own_requests_support import history_lab, providers
from tests.own_requests.reprint_test_support import reprint_lab, terminal_request

pytestmark = pytest.mark.django_db(transaction=True)


def test_reprint_api_commits_when_after_commit_row_lookup_fails(
    reprint_lab, providers, monkeypatch, caplog,
):
    lab = reprint_lab
    original, _ = terminal_request(lab)
    manager = MachineServiceRequest.objects
    real_select_related = manager.select_related
    failed_ids = []
    failure = RuntimeError("Synthetic callback row lookup unavailable")

    class CallbackQuery:
        def __init__(self, queryset):
            self.queryset = queryset

        def __getattr__(self, name):
            return getattr(self.queryset, name)

        def get(self, *args, **kwargs):
            if not args and set(kwargs) == {"pk"} and kwargs["pk"] != original.pk:
                # The row and audit are already visible outside any app transaction.
                child = manager.get(pk=kwargs["pk"])
                assert child.status == "accepted" and child.reprint_of_id == original.pk
                assert connection.get_autocommit() and not connection.in_atomic_block
                assert AuditLog.objects.filter(
                    action="machine_service.reprint_created", target_id=str(child.pk),
                ).exists()
                failed_ids.append(child.pk)
                raise failure
            return self.queryset.get(*args, **kwargs)

    def select_related(*fields, **kwargs):
        queryset = real_select_related(*fields, **kwargs)
        if fields == ("bucket__machine__makerspace", "queue__makerspace") and not kwargs:
            return CallbackQuery(queryset)
        return queryset

    # Only the callback's exact manager/query path changes. Workflow locks,
    # source gates, permission queries, serialization and all domain actions run.
    monkeypatch.setattr(manager, "select_related", select_related)
    client = APIClient(raise_request_exception=False)
    client.force_authenticate(user=lab.actor)
    assert connection.get_autocommit() and not connection.in_atomic_block

    with caplog.at_level(logging.ERROR, logger="django.db.backends.base"):
        response = client.post(
            reverse("admin-machine-service-request-reprint", args=[original.pk]), {}, format="json",
        )

    assert len(failed_ids) == 1
    child = MachineServiceRequest.objects.get(pk=failed_ids[0])
    assert child.status == "accepted" and child.member_id == lab.user.pk
    assert AuditLog.objects.filter(
        action="machine_service.reprint_created", target_id=str(child.pk), actor=lab.actor,
    ).count() == 1
    assert response.status_code == 200
    assert response.data["id"] == child.pk
    assert connection.get_autocommit() and not connection.in_atomic_block
    assert any(
        record.name == "django.db.backends.base"
        and "during transaction (" in record.getMessage()
        and "on_commit()" in record.getMessage()
        and record.exc_info and record.exc_info[1] is failure
        for record in caplog.records
    )
    assert providers == []
    assert not NotificationDeliveryLog.objects.exists() and not Notification.objects.exists()
    assert not EmailLog.objects.exists()
