"""Coordinator admission/failure contracts using process adapters, not providers."""

from dataclasses import replace
import json

import pytest

from apps.backup.compound_restore_coordinator import run_compound_restore
from apps.backup.compound_restore_types import CompoundRestoreRefused
from tests.backup.obsolete_contract_coordinator import (
    assert_no_effects, prepared_coordinator,
)


@pytest.mark.parametrize("rejected", ("topology", "non-routable-database"))
def test_unsafe_sibling_admission_refuses_before_effects(monkeypatch, tmp_path, rejected):
    _fixture, arguments, events = prepared_coordinator(monkeypatch, tmp_path)
    pointer, database = arguments["pointer"], arguments["database"]
    if rejected == "topology":
        original = pointer.preflight
        monkeypatch.setattr(pointer, "preflight", lambda **kwargs: replace(
            original(**kwargs), safe_sibling_lifecycle=False,
        ))
        match, probes = "safe sibling lifecycle", ("pointer-preflight",)
    else:
        original = database.preflight
        monkeypatch.setattr(database, "preflight", lambda: {
            **original(), "non_routable_sibling": False,
        })
        match, probes = "non routable sibling", ("pointer-preflight", "database-preflight")

    with pytest.raises(CompoundRestoreRefused, match=match):
        run_compound_restore(**arguments)

    assert_no_effects(arguments, events, probes=probes)


def test_coordinator_grant_failure_stops_before_rehydration_and_cutover(monkeypatch, tmp_path):
    _fixture, arguments, events = prepared_coordinator(monkeypatch, tmp_path)

    def refuse(_sibling):
        events.append("grant-refused")
        raise RuntimeError("injected grant refusal")

    monkeypatch.setattr(arguments["database"], "apply_runtime_ownership_and_grants", refuse)
    with pytest.raises(RuntimeError, match="injected grant refusal"):
        run_compound_restore(**arguments)

    assert events[-1] == "grant-refused"
    assert arguments["pointer"].current == "old"
    assert not any(event in events for event in (
        "not-restored-and-reservations", "fences-installed", "object-write",
        "candidate-backend-without-migrate", "pointer-cutover", "start:backend,worker,beat",
    ))
    assert arguments["capability_journal"].armed is None
    records = [json.loads(line) for path in arguments["ops_dir"].glob("runs/*.jsonl")
               for line in path.read_text().splitlines()]
    assert records[-1]["phase"] == "roles-and-grants"
    assert records[-1]["state"] == "begun"
    assert not any(record["phase"] == "rehydrate-not-restored-and-reservations" for record in records)
