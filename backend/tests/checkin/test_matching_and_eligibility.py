"""P0: identity resolution and the gate.

The roster carries no secret, so matching is the whole of identity here. These
tests pin the exact strictness chosen -- normalised-exact, no fuzzy -- using
SYNTHETIC names that reproduce the shapes seen upstream (a trailing period, a
double space, all-caps) rather than real people's names.
"""

from datetime import datetime, timedelta, timezone

import pytest

from apps.checkin.client import CheckinEntry
from apps.checkin.eligibility import (
    ELIGIBLE,
    REASON_EXPIRED,
    REASON_PROJECT,
    REASON_PURPOSE,
    REASON_SPACE,
    is_eligible,
    refusal_reason,
)
from apps.checkin.matching import candidates, normalize

NOW = datetime(2026, 9, 3, 14, 0, tzinfo=timezone.utc)
LATER = NOW + timedelta(hours=1)
EARLIER = NOW - timedelta(hours=1)


def entry(**overrides):
    base = dict(
        mid=1,
        name="Ada Example",
        avatar="",
        purpose="Working on a project",
        project_name="Metrocard",
        check_in_time=EARLIER,
        check_out_time=LATER,
        space_id=1,
    )
    base.update(overrides)
    return CheckinEntry(**base)


# --- normalisation -------------------------------------------------------------

@pytest.mark.parametrize("typed,stored", [
    ("ada example", "Ada Example"),
    ("ADA EXAMPLE", "Ada Example"),
    ("  Ada   Example  ", "Ada Example"),
    ("Ada  Example", "Ada Example"),          # double space upstream
    ("Bee Sample", "Bee  Sample"),            # double space in the roster
])
def test_normalised_names_match(typed, stored):
    assert normalize(typed) == normalize(stored)


def test_trailing_period_is_significant():
    """Deliberate: dropping it would merge two people we cannot tell apart."""
    assert normalize("C Sample .") != normalize("C Sample")


@pytest.mark.parametrize("typed", ["", "   ", None])
def test_blank_input_matches_nothing(typed):
    assert candidates([entry()], typed) == []


def test_partial_name_does_not_match():
    assert candidates([entry(name="Ada Example")], "Ada") == []


def test_identical_names_both_returned_for_avatar_disambiguation():
    roster = [entry(mid=1, name="Ada Example"), entry(mid=2, name="ada  EXAMPLE")]
    assert sorted(e.mid for e in candidates(roster, "Ada Example")) == [1, 2]


# --- the gate ------------------------------------------------------------------

def test_eligible_entry_passes():
    assert refusal_reason(entry(), NOW, space_id=1) == ELIGIBLE
    assert is_eligible(entry(), NOW, space_id=1)


@pytest.mark.parametrize("purpose", ["Visiting", "Self Learning", "Attending an event", ""])
def test_wrong_purpose_is_refused(purpose):
    assert refusal_reason(entry(purpose=purpose), NOW, space_id=1) == REASON_PURPOSE


def test_purpose_match_is_normalised():
    assert refusal_reason(entry(purpose="  working ON a  project "), NOW, space_id=1) == ELIGIBLE


@pytest.mark.parametrize("project", ["", "   ", "\t\n"])
def test_blank_or_whitespace_project_is_refused(project):
    assert refusal_reason(entry(project_name=project), NOW, space_id=1) == REASON_PROJECT


def test_purpose_is_reported_before_project():
    """Choosing the purpose upstream is what makes the project field appear, so
    telling someone to fill in a field they do not have would be a dead end."""
    both_wrong = entry(purpose="Visiting", project_name="")
    assert refusal_reason(both_wrong, NOW, space_id=1) == REASON_PURPOSE


def test_expired_checkout_is_refused():
    assert refusal_reason(entry(check_out_time=EARLIER), NOW, space_id=1) == REASON_EXPIRED


def test_missing_checkout_does_not_expire():
    assert refusal_reason(entry(check_out_time=None), NOW, space_id=1) == ELIGIBLE


def test_other_space_is_refused_before_anything_else():
    other = entry(space_id=2, purpose="Visiting", project_name="")
    assert refusal_reason(other, NOW, space_id=1) == REASON_SPACE


def test_space_check_is_skipped_when_unbound():
    assert refusal_reason(entry(space_id=99), NOW, space_id=None) == ELIGIBLE


def test_required_purpose_is_configurable(settings):
    """One upstream rename must be fixable without a deploy."""
    settings.CHECKIN_REQUIRED_PURPOSE = "Building something"
    assert refusal_reason(entry(), NOW, space_id=1) == REASON_PURPOSE
    assert refusal_reason(entry(purpose="Building something"), NOW, space_id=1) == ELIGIBLE
