"""P0: the roster client's fail-closed contract.

Every test here asserts a REFUSAL or a deliberate survival, because both directions
are dangerous. Reading a broken response as "nobody is checked in" would tell a
person standing in the building that they are not in it; denying the whole building
because one row is malformed would be an outage caused by a third party's typo.
"""

import gzip
import io
import json
from datetime import datetime, timedelta, timezone

import pytest
import requests
from urllib3.response import HTTPResponse

from apps.checkin import client
from apps.checkin.client import CheckinUnavailable


NOW = datetime(2026, 9, 3, 14, 0, tzinfo=timezone.utc)


def row(**overrides):
    base = {
        "mid": 443,
        "name": "Rishi Krishna",
        "avatar": "https://example.invalid/a.jpg",
        "purpose": "Working on a project",
        "projectName": "Metrocard",
        "checkInTime": "2026-09-03T13:43:12.415279Z",
        "checkOutTime": "2026-09-03T15:00:00Z",
        "spaceId": 1,
    }
    base.update(overrides)
    return base


def parse(rows):
    return client._parse(json.dumps(rows).encode())


def _compressed_response(body, *, status_code=200):
    compressed = gzip.compress(body)
    response = requests.Response()
    response.status_code = status_code
    response.headers["Content-Encoding"] = "gzip"
    response.headers["Content-Length"] = str(len(compressed))
    response.raw = HTTPResponse(
        body=io.BytesIO(compressed),
        headers=response.headers,
        preload_content=False,
    )
    return response


# --- the happy path, pinned so the shape cannot drift silently ---------------

def test_parses_a_well_formed_row():
    entry, = parse([row()])
    assert entry.mid == 443
    assert entry.name == "Rishi Krishna"
    assert entry.purpose == "Working on a project"
    assert entry.project_name == "Metrocard"
    assert entry.space_id == 1
    assert entry.check_out_time == datetime(2026, 9, 3, 15, 0, tzinfo=timezone.utc)


def test_empty_roster_is_not_an_error():
    """Nobody checked in is a normal Tuesday morning, not a broken upstream."""
    assert parse([]) == []


def test_fetch_decodes_a_compressed_roster(monkeypatch, settings):
    body = json.dumps([row()]).encode()
    settings.CHECKIN_API_URL = "https://example.invalid/checkins"
    settings.CHECKIN_MAX_RESPONSE_BYTES = len(body)
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: _compressed_response(body))

    assert client._get_body() == body


@pytest.mark.parametrize("status_code", [200, 203, 206, 299])
def test_fetch_accepts_the_complete_success_status_family(
    monkeypatch, settings, status_code
):
    body = json.dumps([row()]).encode()
    settings.CHECKIN_API_URL = "https://example.invalid/checkins"
    monkeypatch.setattr(
        requests,
        "get",
        lambda *args, **kwargs: _compressed_response(body, status_code=status_code),
    )

    assert client._get_body() == body


@pytest.mark.parametrize("status_code", [199, 300, 404, 500])
def test_fetch_refuses_every_non_success_status(monkeypatch, settings, status_code):
    body = json.dumps([row()]).encode()
    settings.CHECKIN_API_URL = "https://example.invalid/checkins"
    monkeypatch.setattr(
        requests,
        "get",
        lambda *args, **kwargs: _compressed_response(body, status_code=status_code),
    )

    with pytest.raises(CheckinUnavailable, match="unavailable"):
        client._get_body()


def test_fetch_caps_the_decoded_response_size(monkeypatch, settings):
    body = json.dumps([row(projectName="x" * 2_000)]).encode()
    settings.CHECKIN_API_URL = "https://example.invalid/checkins"
    settings.CHECKIN_MAX_RESPONSE_BYTES = len(body) - 1
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: _compressed_response(body))

    with pytest.raises(CheckinUnavailable, match="too large"):
        client._get_body()


# --- refusals: the body is not a roster we can trust -------------------------

def test_non_json_body_refuses():
    with pytest.raises(CheckinUnavailable):
        client._parse(b"<html>502 Bad Gateway</html>")


def test_non_list_body_refuses():
    with pytest.raises(CheckinUnavailable):
        client._parse(json.dumps({"detail": "nope"}).encode())


def test_all_rows_unparseable_refuses():
    """A non-empty body that yields nothing is a contract change, not an empty room."""
    with pytest.raises(CheckinUnavailable):
        parse([{"garbage": True}, {"also": "garbage"}])


def test_too_many_rows_refuses(settings):
    settings.CHECKIN_MAX_ROWS = 2
    with pytest.raises(CheckinUnavailable):
        parse([row(mid=1), row(mid=2), row(mid=3)])


# --- survivals: one bad row must not deny everyone else ----------------------

def test_one_bad_row_among_good_ones_is_skipped():
    entries = parse([row(mid=1), {"garbage": True}, row(mid=2)])
    assert sorted(e.mid for e in entries) == [1, 2]


@pytest.mark.parametrize("bad", [
    {"mid": 0},              # not positive
    {"mid": -5},
    {"mid": "443"},          # not an int
    {"mid": True},           # bool is an int subclass and must not pass
    {"name": ""},            # unmatchable
    {"name": "   "},
    {"name": None},
])
def test_individually_invalid_rows_are_dropped(bad):
    entries = parse([row(**bad), row(mid=999)])
    assert [e.mid for e in entries] == [999]


# --- ambiguity: a repeated mid is dropped, and only that mid -----------------

def test_duplicate_mid_drops_only_the_ambiguous_person():
    entries = parse([row(mid=7, projectName="A"), row(mid=7, projectName="B"), row(mid=8)])
    assert [e.mid for e in entries] == [8]


# --- bounds ------------------------------------------------------------------

def test_overlong_strings_are_truncated_not_rejected():
    entry, = parse([row(name="x" * 5000, projectName="y" * 5000)])
    assert len(entry.name) == client.MAX_NAME
    assert len(entry.project_name) == client.MAX_PROJECT


def test_mid_must_survive_a_javascript_number_round_trip_exactly():
    entry, = parse([row(mid=client.MAX_MID)])
    assert entry.mid == 9_007_199_254_740_991

    with pytest.raises(CheckinUnavailable, match="could not be parsed"):
        parse([row(mid=client.MAX_MID + 1)])


def test_missing_project_becomes_empty_string_not_none():
    entry, = parse([row(projectName=None)])
    assert entry.project_name == ""


def test_boolean_space_id_is_not_accepted_as_integer_space_one():
    entry, = parse([row(spaceId=True)])
    assert entry.space_id is None


# --- timestamps ---------------------------------------------------------------

def test_naive_timestamp_is_treated_as_absent():
    """Guessing a timezone would silently shift a checkout window."""
    entry, = parse([row(checkOutTime="2026-09-03T15:00:00")])
    assert entry.check_out_time is None


def test_unparseable_timestamp_does_not_drop_the_row():
    entry, = parse([row(checkOutTime="whenever")])
    assert entry.mid == 443
    assert entry.check_out_time is None
