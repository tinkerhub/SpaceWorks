import ipaddress
import json
import logging
import re
from datetime import UTC, datetime
from functools import lru_cache
from uuid import uuid4

import redis
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from config.client_ip import get_throttle_client_ip

logger = logging.getLogger(__name__)

BUCKET_TTL_SECONDS = 2 * 24 * 60 * 60
KEY_PREFIX = "apiclients:usage"
SIGNED_KIND = "signed"
BROWSER_KIND = "browser"
BUCKET_PATTERN = re.compile(
    rf"{re.escape(KEY_PREFIX)}:(?:{SIGNED_KIND}|{BROWSER_KIND}):([0-9]{{12}})"
    r"(?::draining(?::[0-9a-f]{32})?)?"
)


@lru_cache(maxsize=4)
def _client_for_url(url):
    return redis.Redis.from_url(url, decode_responses=True)


def get_redis_client():
    """Return the configured Redis cache client, or None for non-Redis installs."""
    config = settings.CACHES.get("default", {})
    if not str(config.get("BACKEND", "")).endswith(".RedisCache"):
        return None
    location = config.get("LOCATION")
    if isinstance(location, (list, tuple)):
        location = location[0] if location else ""
    return _client_for_url(str(location)) if location else None


def bucket_key(kind, observed_at):
    minute = observed_at.astimezone(UTC).replace(second=0, microsecond=0)
    return f"{KEY_PREFIX}:{kind}:{minute:%Y%m%d%H%M}"


def record_signed_client_observation(request, client):
    _record_observation(SIGNED_KIND, request, client.client_id)


def record_browser_client_observation(request, client):
    # Browser identity is public and forgeable, so it has a distinct namespace.
    _record_observation(BROWSER_KIND, request, client.client_id)


def _record_observation(kind, request, client_id):
    try:
        observed_at = timezone.now()
        redis_client = get_redis_client()
        if redis_client is None:
            return
        key = bucket_key(kind, observed_at)
        payload = json.dumps(
            {
                "timestamp": observed_at.isoformat(),
                "resolved_ip": _resolved_ip(request),
            },
            separators=(",", ":"),
        )
        pipeline = redis_client.pipeline()
        pipeline.hset(key, client_id, payload)
        pipeline.expire(key, BUCKET_TTL_SECONDS)
        pipeline.execute()
    except Exception:  # noqa: BLE001 - telemetry must never fail authentication
        logger.warning(
            "ApiClient usage telemetry Redis write failed",
            extra={"client_id": client_id, "telemetry_kind": kind},
            exc_info=True,
        )


def _resolved_ip(request):
    return _normalize_ip(get_throttle_client_ip(request))


def _normalize_ip(raw):
    try:
        return str(ipaddress.ip_address(raw)) if raw else None
    except (TypeError, ValueError):
        return None


def flush_usage_observations(*, now=None, redis_client=None):
    """Persist closed Redis buckets with one monotonic bulk update."""
    redis_client = redis_client or get_redis_client()
    if redis_client is None:
        return 0
    current_minute = (now or timezone.now()).astimezone(UTC).replace(
        second=0, microsecond=0
    )
    newest = {}
    consumed_keys = []
    for kind in (SIGNED_KIND, BROWSER_KIND):
        for raw_key in redis_client.scan_iter(match=f"{KEY_PREFIX}:{kind}:*"):
            key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
            bucket = _parse_bucket(key)
            if bucket is None or bucket >= current_minute:
                continue
            # Retry detached buckets in place; concurrent retries are monotonic in DB.
            drained_key = key
            if ":draining" not in key:
                # Detach atomically so late writes recreate the original bucket. Keep
                # each detached generation immutable, including after a failed flush.
                # RENAMENX preserves the TTL and cannot overwrite an existing drain.
                drained_key = f"{key}:draining:{uuid4().hex}"
                try:
                    if not redis_client.renamenx(key, drained_key):
                        continue
                except Exception as exc:
                    # Only a missing source is an expected concurrent claim. Other
                    # Redis failures must remain visible to operators.
                    if (
                        isinstance(exc, redis.ResponseError)
                        and str(exc) == "no such key"
                    ):
                        continue
                    logger.warning(
                        "api_client_usage_bucket_detach_failed",
                        extra={"bucket": key},
                        exc_info=True,
                    )
                    continue
            consumed_keys.append(drained_key)
            for raw_client_id, raw_payload in redis_client.hgetall(drained_key).items():
                client_id = (
                    raw_client_id.decode()
                    if isinstance(raw_client_id, bytes)
                    else raw_client_id
                )
                observation = _parse_observation(raw_payload)
                if observation is None:
                    continue
                lookup = (kind, client_id)
                if lookup not in newest or observation[0] > newest[lookup][0]:
                    newest[lookup] = observation

    updated = _bulk_update_observations(newest)
    if consumed_keys:
        redis_client.delete(*consumed_keys)
    return updated


def _parse_bucket(key):
    match = BUCKET_PATTERN.fullmatch(key)
    if match is None:
        return None
    try:
        return datetime.strptime(match[1], "%Y%m%d%H%M").replace(tzinfo=UTC)
    except ValueError:
        return None


def _parse_observation(raw_payload):
    try:
        if isinstance(raw_payload, bytes):
            raw_payload = raw_payload.decode()
        payload = json.loads(raw_payload)
        observed_at = parse_datetime(payload["timestamp"])
        if observed_at is None:
            return None
        if timezone.is_naive(observed_at):
            observed_at = timezone.make_aware(observed_at, UTC)
        return observed_at, _normalize_ip(payload.get("resolved_ip"))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _bulk_update_observations(newest):
    from apps.apiclients.models import ApiClient

    client_ids = {client_id for _kind, client_id in newest}
    if not client_ids:
        return 0
    with transaction.atomic():
        clients = list(
            ApiClient.objects.select_for_update().filter(client_id__in=client_ids).order_by("pk")
        )
        changed = []
        for client in clients:
            candidates = [newest.get((SIGNED_KIND, client.client_id))]
            if client.client_type == BROWSER_KIND:
                candidates.append(newest.get((BROWSER_KIND, client.client_id)))
            observation = max(
                (item for item in candidates if item),
                key=lambda item: item[0],
                default=None,
            )
            if observation is None or (
                client.last_seen_at is not None and observation[0] <= client.last_seen_at
            ):
                continue
            client.last_seen_at, client.last_seen_ip = observation
            changed.append(client)
        if changed:
            ApiClient.objects.bulk_update(changed, ["last_seen_at", "last_seen_ip"])
    return len(changed)
