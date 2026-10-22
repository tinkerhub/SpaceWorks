"""Network fakes for the per-makerspace roster transport.

DNS is faked at `socket.getaddrinfo` inside the shared outbound guard, and the pinned
HTTPS connection is replaced, so tests exercise the real guard and the real response
handling without touching the network.
"""

import ipaddress
import json
import socket

PUBLIC_IP = "93.184.216.34"


def answers(*ips, port=443):
    return [
        (socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))
        for ip in ips
    ]


def fake_dns(monkeypatch, mapping):
    """`mapping`: hostname -> list of IPs. IP literals resolve to themselves; any
    other unknown host fails to resolve."""

    def getaddrinfo(host, port, *args, **kwargs):
        try:
            return answers(str(ipaddress.ip_address(host)), port=port)
        except ValueError:
            pass
        if host not in mapping:
            raise socket.gaierror("unknown host")
        return answers(*mapping[host], port=port)

    monkeypatch.setattr("apps.integrations.webhook_validation.socket.getaddrinfo", getaddrinfo)


class FakeResponse:
    def __init__(self, status=200, body=b"[]", headers=None):
        self.status = status
        self._body = body
        self._headers = {key.lower(): value for key, value in (headers or {}).items()}

    def getheader(self, name, default=None):
        return self._headers.get(name.lower(), default)

    def read(self, amount=None):
        return self._body if amount is None else self._body[:amount]


def fake_upstream(monkeypatch, routes):
    """`routes`: hostname -> FakeResponse, or an exception instance to raise.

    Returns the list of (hostname, pinned ip, path) connections that were attempted.
    """
    calls = []

    class FakeConnection:
        def __init__(self, target, address):
            self.target = target
            self.address = address
            self.timeout = None

        def request(self, method, path, headers=None):
            calls.append((self.target.hostname, self.address.sockaddr[0], path))
            self._outcome = routes[self.target.hostname]
            if isinstance(self._outcome, BaseException):
                raise self._outcome

        def getresponse(self):
            return self._outcome

        def close(self):
            pass

    monkeypatch.setattr("apps.checkin.transport._PinnedHTTPSConnection", FakeConnection)
    return calls


def roster_body(*rows):
    return json.dumps(list(rows)).encode()


def row(mid=443, name="Ada Example", space_id=1, purpose="Working on a project",
        project="Metrocard"):
    return {
        "mid": mid,
        "name": name,
        "avatar": "",
        "purpose": purpose,
        "projectName": project,
        "checkInTime": "2026-10-22T09:00:00+00:00",
        "checkOutTime": None,
        "spaceId": space_id,
    }
