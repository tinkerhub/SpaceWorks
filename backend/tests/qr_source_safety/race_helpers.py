"""Concurrent committed fixture changes; retain complete after-winner snapshots."""
from django.db import connection

from apps.boxes.models import QrCode
from tests.qr_target_safety_helpers import target


def backend_pid():
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_backend_pid()")
        return cursor.fetchone()[0]


def change_qr(lab, case, mutation, replacement):
    query = QrCode.objects.filter(pk=case.qr.pk)
    if mutation == "deleted":
        query.delete()
    else:
        query.update(makerspace_id=(lab.other.pk if mutation == "moved" else lab.home.pk),
                     target_type="product", target_id=replacement.pk)


def replacement(lab, mutation):
    return target(lab.other if mutation == "moved" else lab.home, "product")


def expected_qr_denial(kind, mutation):
    return 404 if kind.startswith("native") or mutation != "retargeted" else 409
