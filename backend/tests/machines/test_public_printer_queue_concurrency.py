"""Two setup calls serialize on PostgreSQL even when no queue exists yet."""
import queue
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import close_old_connections, connection, transaction

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.machines.models import MachineType, ServiceQueue
from apps.machines.printer_capabilities import PRINTER_CONFIG
from apps.machines.service_public_queue import enable_public_queue
from apps.makerspaces.models import Makerspace
from tests.accounts.test_password_reset_endpoint_concurrency import _wait_until_lock_wait
from tests.return_helpers import make_member, make_space

pytestmark = pytest.mark.django_db(transaction=True)


def test_concurrent_initial_setup_creates_one_queue_and_one_audit():
    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL row locks and separate connections")
    # Transactional flushes remove migration-seeded types between tests.
    printer, _ = MachineType.objects.get_or_create(
        makerspace=None, slug="3d_printer", defaults={
            "name": "3D printer", "is_builtin": True,
            "managing_action": "manage_printing", "capability_config": PRINTER_CONFIG,
        },
    )
    space = make_space("concurrent-public-queue")
    actor = make_member("concurrent-public-queue", space)
    pid_queue = queue.Queue()
    before = AuditLog.objects.count()

    def competing_setup():
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                pid_queue.put(cursor.fetchone()[0])
            return enable_public_queue(User.objects.get(pk=actor.pk), Makerspace.objects.get(pk=space.pk))
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=1) as executor:
        with transaction.atomic():
            Makerspace.objects.select_for_update().get(pk=space.pk)
            competitor = executor.submit(competing_setup)
            _wait_until_lock_wait(pid_queue.get(timeout=5))
            first = enable_public_queue(actor, space)
        second = competitor.result(timeout=10)
    assert first == second
    created = ServiceQueue.objects.get(makerspace=space)
    assert created.machine_type == printer and created.is_active
    assert first["queue_id"] == created.pk
    assert AuditLog.objects.count() == before + 1
    assert AuditLog.objects.filter(makerspace=space, action="machine_service.public_queue_created").count() == 1
