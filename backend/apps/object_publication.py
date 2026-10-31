"""Bounded, validated, create-once publication of a staged object.

No database dependency: lifecycle owners supply exclusion around metadata and cleanup.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from tempfile import SpooledTemporaryFile

from botocore.exceptions import BotoCoreError, ClientError

from apps.evidence.storage import StorageUnavailable


class InvalidObjectSize(Exception):
    def __init__(self, size):
        self.size = size
        super().__init__("Uploaded object is empty or exceeds its size limit.")


@dataclass
class Snapshot:
    body: object
    size: int
    content_type: str
    metadata: dict

    def data(self):
        self.body.seek(0)
        return self.body.read()


def _status(exc):
    return exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")


def _missing(exc):
    status = _status(exc)
    code = exc.response.get("Error", {}).get("Code")
    if status is not None and status != 404:
        return False
    return code in {"404", "NoSuchKey", "NotFound"} or (not code and status == 404)


@contextmanager
def snapshot(client, bucket, key, max_bytes):
    """Read one GET, observing at most max+1 bytes; close both streams on every path."""
    spool = SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b")
    body = None
    try:
        try:
            response = client.get_object(Bucket=bucket, Key=key)
        except ClientError as exc:
            if _missing(exc):
                yield None
                return
            raise StorageUnavailable from exc
        except Exception as exc:
            # Transport boundary only: unexpected SDK failures do not enable fallback.
            raise StorageUnavailable from exc
        if not isinstance(response, dict):
            raise StorageUnavailable("Malformed object-storage read response.")
        body = response.get("Body")
        if not callable(getattr(body, "read", None)):
            raise StorageUnavailable("Malformed object-storage read response.")
        size = 0
        while size <= max_bytes:
            try:
                chunk = body.read(min(64 * 1024, max_bytes + 1 - size))
            except Exception as exc:
                raise StorageUnavailable from exc
            if not isinstance(chunk, bytes):
                raise StorageUnavailable("Malformed object-storage body.")
            if not chunk:
                break
            spool.write(chunk)
            size += len(chunk)
        if not 1 <= size <= max_bytes:
            raise InvalidObjectSize(size)
        spool.seek(0)
        yield Snapshot(
            spool, size, str(response.get("ContentType", "")).lower().strip(),
            response.get("Metadata", {}),
        )
    except (BotoCoreError, ClientError, OSError) as exc:
        raise StorageUnavailable from exc
    finally:
        try:
            if body is not None:
                try:
                    body.close()
                except Exception as exc:
                    raise StorageUnavailable from exc
        finally:
            spool.close()


def validate_existing(client, bucket, key, max_bytes, validator):
    with snapshot(client, bucket, key, max_bytes) as current:
        return None if current is None else validator(current)


def publish(client, *, bucket, key, staging_key, max_bytes, validator):
    """Existing final wins. Conditional conflicts always validate the actual winner."""
    current = validate_existing(client, bucket, key, max_bytes, validator)
    if current is not None:
        return current
    with snapshot(client, bucket, staging_key, max_bytes) as source:
        if source is None:
            return None
        result = validator(source)  # Domain validation precedes *any* final write.
        for _attempt in range(3):
            source.body.seek(0)
            try:
                client.put_object(
                    Bucket=bucket, Key=key, Body=source.body,
                    ContentType=result.content_type, Metadata=source.metadata,
                    IfNoneMatch="*",
                )
            except ClientError as exc:
                code = str(exc.response.get("Error", {}).get("Code", ""))
                status = _status(exc)
                if status not in {409, 412} and code not in {
                    "ConditionalRequestConflict", "PreconditionFailed", "409", "412",
                }:
                    raise StorageUnavailable from exc
                winner = validate_existing(client, bucket, key, max_bytes, validator)
                if winner is not None:
                    return winner
                if status == 412 or code in {"PreconditionFailed", "412"}:
                    raise StorageUnavailable from exc
                continue
            except Exception as exc:
                # Includes SDKs without IfNoneMatch support. Never fall back to COPY.
                raise StorageUnavailable from exc
            winner = validate_existing(client, bucket, key, max_bytes, validator)
            if winner is None:
                raise StorageUnavailable
            return winner
    raise StorageUnavailable
