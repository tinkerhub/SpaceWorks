"""NO_MEMBERSHIP checks only dependencies that can survive target projection."""

import csv

import pytest

from apps.tenant_migration.archive_stream import PORTABLE_DATASETS, PortableArchive
from apps.tenant_migration.identity_decision_validation import (
    validate_membership_dispositions,
)
from apps.tenant_migration.models_import_job import ImportIdentityDecision
from apps.tenant_migration.protocol_errors import MembershipDependencyError
from apps.tenant_migration.target_projection import ROW_POLICIES, RowDisposition, RowPolicy


@pytest.fixture
def archived_rows():
    # Source archives contain personal scope rows that target projection drops.
    return {
        "makerspaces.MakerspaceMembership": [
            {"id": "41", "user_id": "7", "makerspace_id": "3", "status": "active"},
        ],
        "machines.MembershipMachineTypeScope": [
            {
                "id": "51",
                "membership_id": "41",
                "machine_type_id": "9",
                "created_at": "2026-09-01T10:00:00+00:00",
            },
        ],
    }


def portable_archive(root, rows):
    # Keep real CSV headers and empty datasets, without exporting from a database.
    assert rows.keys() <= PORTABLE_DATASETS.keys(), "Fixture rows must use real portable datasets"
    for label, dataset in PORTABLE_DATASETS.items():
        path = root / dataset.path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=[column.name for column in dataset.columns],
            )
            writer.writeheader()
            writer.writerows(rows.get(label, ()))
    return PortableArchive(root)


def validate_no_membership(archive):
    validate_membership_dispositions(
        archive,
        [{
            "source_user_id": "7",
            "membership_disposition": (
                ImportIdentityDecision.MembershipDisposition.NO_MEMBERSHIP
            ),
        }],
    )


def test_dropped_personal_scope_does_not_require_membership(tmp_path, archived_rows):
    validate_no_membership(portable_archive(tmp_path, archived_rows))


@pytest.mark.parametrize(
    ("label", "dependent"),
    [
        (
            "makerspaces.MemberProfile",
            {"id": "61", "membership_id": "41", "is_visible": "true"},
        ),
        (
            "presence.PresenceSession",
            {
                "id": "71",
                "membership_id": "41",
                "member_id": "7",
                "makerspace_id": "3",
                "started_at": "2026-09-01T10:00:00+00:00",
                "expires_at": "2026-09-01T12:00:00+00:00",
            },
        ),
    ],
)
def test_retained_dependent_still_requires_membership(
    tmp_path, archived_rows, label, dependent,
):
    archived_rows[label] = [dependent]

    with pytest.raises(MembershipDependencyError) as error:
        validate_no_membership(portable_archive(tmp_path, archived_rows))

    assert str(error.value) == (
        "no_membership would retain rows with a required membership reference: "
        f"{label}=1."
    )


def test_conditional_drop_does_not_exempt_surviving_profile(
    tmp_path, archived_rows, monkeypatch,
):
    # Simulate a future rule on a real portable, required-membership model. The
    # visible profile survives a DROP limited to hidden profiles.
    label = "makerspaces.MemberProfile"
    monkeypatch.setitem(
        ROW_POLICIES,
        label,
        RowPolicy(
            RowDisposition.DROP,
            "Only hidden profiles are dropped in this scenario.",
            condition=("is_visible", False),
        ),
    )
    archived_rows[label] = [
        {"id": "61", "membership_id": "41", "is_visible": "true"},
    ]

    with pytest.raises(MembershipDependencyError, match=r"makerspaces\.MemberProfile=1"):
        validate_no_membership(portable_archive(tmp_path, archived_rows))
