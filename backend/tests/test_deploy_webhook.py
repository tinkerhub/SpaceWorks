"""Signed release queue and deployment proxy boundaries; no Django or database needed."""

from email.message import Message
import hashlib
import hmac
import importlib.util
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml


BACKEND = Path(__file__).resolve().parents[1]
ROOT = Path("/workspace") if Path("/workspace/install.sh").exists() else BACKEND.parent
SPEC = importlib.util.spec_from_file_location("deploy_webhook", BACKEND / "scripts/deploy_webhook.py")
webhook = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(webhook)
REPOSITORY = "tinkerhub/SpaceWorks"
SECRET = "private-webhook-secret"
DELIVERY = "12345678-1234-1234-1234-123456789abc"
TAG = "v1.2.3-main.42.abcdef123456"


@pytest.fixture
def receiver(tmp_path, monkeypatch):
    # The production queue is POSIX. Windows cannot open/fsync a directory or fchmod.
    # Exercise publication/dedupe on Windows while retaining real fsync on Linux CI.
    if os.name == "nt":
        monkeypatch.setattr(webhook, "sync_directory", lambda path: None)
        monkeypatch.setattr(webhook.os, "fchmod", lambda fd, mode: None, raising=False)
    return webhook.Receiver(REPOSITORY, SECRET, tmp_path)


def payload():
    return {"action": "published", "repository": {"full_name": REPOSITORY},
            "release": {"draft": False, "prerelease": False, "tag_name": TAG}}


def signed(data, event="release", delivery=DELIVERY):
    body = json.dumps(data).encode()
    return {
        "X-Hub-Signature-256": "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest(),
        "X-GitHub-Event": event, "X-GitHub-Delivery": delivery,
    }, body


def test_signed_release_queues_only_tag_and_delivery(receiver, tmp_path):
    data = payload()
    data["release"]["body"] = "$(touch /host/should-never-run)"
    assert receiver.receive(*signed(data)) == (202, "queued")
    assert json.loads((tmp_path / f"{DELIVERY}.json").read_text()) == {
        "tag": TAG, "delivery": DELIVERY,
    }
    assert (tmp_path / ".deliveries" / DELIVERY).exists()


def test_bad_signature_does_not_write(receiver, tmp_path):
    headers, body = signed(payload())
    headers["X-Hub-Signature-256"] = "sha256=" + "0" * 64
    assert receiver.receive(headers, body) == (403, "signature_refused")
    assert list(tmp_path.iterdir()) == []


def test_empty_secret_disables_receiver(tmp_path):
    disabled = webhook.Receiver(REPOSITORY, "", tmp_path)
    assert disabled.receive(*signed(payload())) == (403, "disabled")
    assert list(tmp_path.iterdir()) == []


def test_signed_ping_does_not_queue(receiver, tmp_path):
    assert receiver.receive(*signed({}, event="ping")) == (200, "ping")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("field,value", [
    ("draft", True), ("prerelease", True), ("repository", "other/SpaceWorks"),
    ("action", "edited"), ("tag_name", "v1.2.3"), ("tag_name", "../../update.sh"),
    ("draft", None), ("prerelease", "false"),
])
def test_ineligible_release_is_ignored(receiver, tmp_path, field, value):
    data = payload()
    if field == "repository":
        data["repository"]["full_name"] = value
    elif field == "action":
        data[field] = value
    else:
        data["release"][field] = value
    assert receiver.receive(*signed(data)) == (202, "ignored")
    assert list(tmp_path.iterdir()) == []


def test_duplicate_survives_consumption_and_restart(receiver, tmp_path):
    assert receiver.receive(*signed(payload())) == (202, "queued")
    (tmp_path / f"{DELIVERY}.json").unlink()
    restarted = webhook.Receiver(REPOSITORY, SECRET, tmp_path)
    assert restarted.receive(*signed(payload())) == (202, "duplicate")
    assert list(tmp_path.glob("*.json")) == []


def test_rate_limit_expires_after_one_minute(tmp_path):
    now = [100.0]
    limited = webhook.Receiver(REPOSITORY, SECRET, tmp_path, limit=2, clock=lambda: now[0])
    assert limited.rate_allowed()
    assert limited.rate_allowed()
    assert not limited.rate_allowed()
    now[0] += 60
    assert limited.rate_allowed()


@pytest.mark.parametrize("body", [b"not-json", b"[]", b"null", b"\xff"])
def test_authenticated_invalid_json(receiver, body):
    headers = {"X-Hub-Signature-256": "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()}
    assert receiver.receive(headers, body) == (400, "invalid_json")


def test_invalid_delivery_and_unwritable_queue(receiver, tmp_path):
    assert receiver.receive(*signed(payload(), delivery="../outside")) == (400, "invalid_delivery")
    (tmp_path / ".deliveries").write_text("blocked")
    assert receiver.receive(*signed(payload())) == (503, "queue_unavailable")
    assert list(tmp_path.glob("*.json")) == []


def post(receiver, headers, body=b"", path="/hooks/deploy"):
    """Invoke real HTTP framing validation without opening a network socket."""
    handler = object.__new__(webhook.Handler)
    handler.server = SimpleNamespace(receiver=receiver)
    handler.path = path
    handler.headers = Message()
    for key, value in headers:
        handler.headers[key] = value
    handler.rfile = io.BytesIO(body)
    results = []
    handler.respond = lambda status, outcome: results.append((status, outcome))
    handler.do_POST()
    return results[0]


@pytest.mark.parametrize("lengths,body,expected", [
    ([], b"", (400, "invalid_length")),
    (["1", "1"], b"x", (400, "invalid_length")),
    (["-1"], b"", (400, "invalid_length")),
    ([str(webhook.MAX_BODY + 1)], b"", (413, "body_too_large")),
    (["3"], b"xx", (400, "incomplete_body")),
])
def test_http_size_and_length_framing(receiver, lengths, body, expected):
    headers = [("Content-Type", "application/json")]
    headers += [("Content-Length", length) for length in lengths]
    assert post(receiver, headers, body) == expected


def test_http_rejects_transfer_encoding_and_rate_limits(receiver):
    headers = [("Content-Type", "application/json"), ("Content-Length", "2"),
               ("Transfer-Encoding", "chunked")]
    assert post(receiver, headers, b"{}") == (400, "invalid_length")
    receiver.limit = 0
    assert post(receiver, headers) == (429, "rate_limited")


def test_a_trickling_client_cannot_hold_the_single_threaded_receiver(receiver, monkeypatch):
    import socket
    import threading
    import time

    monkeypatch.setattr(webhook, "REQUEST_DEADLINE", 1)
    server = webhook.HTTPServer(("127.0.0.1", 0), webhook.Handler)
    server.receiver = receiver
    threading.Thread(target=server.handle_request, daemon=True).start()
    client = socket.create_connection(server.server_address, timeout=10)
    started = time.monotonic()
    try:
        client.sendall(b"POST /hooks/deploy HTTP/1.0\r\n")
        # One byte inside every idle gap: the 5 s idle timeout alone would never fire.
        while time.monotonic() - started < 8:
            try:
                client.sendall(b"X")
                client.settimeout(0.01)  # portable non-blocking peek (no MSG_DONTWAIT on Windows)
                if client.recv(1) == b"":
                    break
            except (BlockingIOError, TimeoutError):
                pass
            except OSError:
                break
            time.sleep(0.3)
    finally:
        client.close()
        server.server_close()
    assert time.monotonic() - started < 4


HOST_ONLY =pytest.mark.skipif(not (ROOT / "install.sh").exists(), reason="requires host checkout")


@HOST_ONLY
@pytest.mark.parametrize("path", ["deploy/Caddyfile", "deploy/Caddyfile.saas", "frontend/nginx.conf"])
def test_deploy_route_reaches_isolated_receiver(path):
    source = (ROOT / path).read_text()
    assert "/hooks/deploy" in source
    assert "deploy-webhook:8081" in source
    if path.endswith("nginx.conf"):
        assert "location = /hooks/deploy" in source
        assert "client_max_body_size 1m;" in source
    else:
        assert source.index("@deploy path") < source.index("@backend path")
        if path.endswith(".saas"):
            snippet = source.split("(backend_paths) {", 1)[1].split("# Expose", 1)[0]
            assert "reverse_proxy @deploy deploy-webhook:8081" in snippet


@HOST_ONLY
@pytest.mark.parametrize("path", ["docker-compose.prod.yml", "docker-compose.yml", "docker-compose.cloud.yml"])
def test_receiver_has_no_host_execution_or_database_authority(path):
    document = yaml.safe_load((ROOT / path).read_text())
    service = document["services"]["deploy-webhook"]
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in service["security_opt"]
    assert service["networks"] == ["deploy-hooks"]
    assert "env_file" not in service
    assert set(service["environment"]) == {"SPACEWORKS_REPOSITORY", "SPACEWORKS_DEPLOY_WEBHOOK_SECRET"}
    assert all("docker.sock" not in volume and ".env" not in volume for volume in service["volumes"])
    assert service["expose"] == ["8081"]
    assert document["networks"]["deploy-hooks"]["internal"] is True
    frontend = document["services"]["frontend"]
    assert set(frontend["networks"]) == {"default", "deploy-hooks"}
    assert frontend["depends_on"]["deploy-webhook"]["condition"] == "service_started"
    if path == "docker-compose.prod.yml":
        # An image rollback must not drop /hooks/deploy, so nginx reads the host-bundle copy.
        assert "./frontend/nginx.conf:/etc/nginx/conf.d/default.conf:ro" in frontend["volumes"]
    if path == "docker-compose.cloud.yml":
        # Cloud is not deployed by the host updater: the receiver stays disabled and queueless.
        assert service["environment"]["SPACEWORKS_DEPLOY_WEBHOOK_SECRET"] == ""
        assert not any("deploy-requests" in volume for volume in service["volumes"])


@HOST_ONLY
@pytest.mark.parametrize("path", ["docker/compose.tls.yml", "docker/compose.saas.yml"])
def test_tls_edges_retain_default_and_deploy_networks(path):
    class ComposeLoader(yaml.SafeLoader):
        pass
    ComposeLoader.add_constructor("!reset", lambda loader, node: None)
    document = yaml.load((ROOT / path).read_text(), Loader=ComposeLoader)
    assert set(document["services"]["caddy"]["networks"]) == {"default", "deploy-hooks"}


@HOST_ONLY
def test_setup_secret_and_retirement_precede_compose():
    source = (ROOT / "setup.sh").read_text()
    helper = (ROOT / "scripts" / "setup-deploy-webhook.sh").read_text()
    compose_records = source.index("\nprepare_compose_wrapper")
    # The receiver reads its secret from .env, so it must exist before Compose records it.
    assert source.index("\nask_deploy_webhook\n") < compose_records
    assert "env_file_append_if_absent .env SPACEWORKS_DEPLOY_WEBHOOK_SECRET" in helper
    assert source.index("\nretire_update_tombstone\n") < source.index('"${COMPOSE[@]}" up')
    assert source.index("\nretire_update_polling\n") < source.index('"${COMPOSE[@]}" up')
    finish = helper.split("finish_deploy_webhook_setup()", 1)[1]
    assert "$secret" not in finish and "${SPACEWORKS_DEPLOY_WEBHOOK_SECRET" not in finish