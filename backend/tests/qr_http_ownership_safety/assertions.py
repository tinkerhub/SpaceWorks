"""Whole-row denial assertions and unmodified SQL observation."""
import json
from contextlib import contextmanager

from django.db import connection

from tests.qr_source_safety.state_helpers import plain, state


def dml(sql):
    return sql.lstrip().upper().startswith(("INSERT ", "UPDATE ", "DELETE ", "MERGE "))


@contextmanager
def statements():
    captured = []

    def observe(execute, sql, params, many, context):
        row = {"sql": sql, "params": tuple(params or ()), "completed": False}
        captured.append(row)
        result = execute(sql, params, many, context)
        row["completed"] = True
        return result

    with connection.execute_wrapper(observe):
        yield captured


def no_gate_or_dml(captured):
    assert not [row for row in captured if dml(row["sql"])], captured
    assert not [row for row in captured
                if '"tenant_migration_sourcemigrationgate"' in row["sql"]], captured


def unavailable(response):
    assert response.status_code == 503, getattr(response, "data", response.content)
    assert json.loads(response.content)["code"] == "tenant_migration_gate_unavailable"


def all_rows(*models):
    return {model._meta.label_lower: plain(list(model.objects.order_by("pk").values()))
            for model in models}


def domain_without_audits():
    rows = state()
    del rows["audit.auditlog"]
    return rows
