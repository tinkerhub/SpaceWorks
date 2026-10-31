"""HOST-ONLY: repository scripts/ and Compose files are absent from backend images."""

import ast
from pathlib import Path

from apps.backup.route_policy import route_allowed
from tests.backup.obsolete_contract_host import (
    assert_restore_grant_edges, assert_privileged_grant_bootstrap,
    assert_legacy_compound_refusal,
)


ROOT = Path(__file__).resolve().parents[3]
PRODUCTION_COMPOSE = ROOT / "docker-compose.prod.yml"


def test_every_python_pg_restore_reprovisions_before_later_django_commands():
    assert_restore_grant_edges()
    assert_privileged_grant_bootstrap()


def test_quarantined_candidate_is_probeable_without_a_migrate_dependency():
    compose = PRODUCTION_COMPOSE.read_text(encoding="utf-8")
    candidate = compose.split("  candidate-backend:", 1)[1].split("\n  frontend:", 1)[0]
    assert "/api/v1/health/readiness/" in candidate
    assert "      migrate:" not in candidate
    assert route_allowed("quarantined", "readiness", "GET")
    assert route_allowed("target_import", "readiness", "GET")


def test_controller_validates_before_claiming_or_pausing():
    assert_legacy_compound_refusal()
    tree = ast.parse((ROOT / "backend/apps/backup/host_restore_lifecycle.py").read_text())
    decision = next(node for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef) and node.name == "decision")
    statements = [ast.unparse(node) for node in decision.body]
    preflights = [i for i, text in enumerate(statements) if text.startswith("i.preflight(")]
    claim = next(i for i, text in enumerate(statements) if "t.control('claim'" in text)
    quiesce = next(i for i, text in enumerate(statements) if "t.control('quiesce'" in text)
    stop = next(i for i, text in enumerate(statements) if "t.compose('stop'" in text)
    assert len(preflights) == 2
    assert preflights[0] < claim < preflights[1] < quiesce < stop
    assert "raise RestoreHostError" in statements[claim]
