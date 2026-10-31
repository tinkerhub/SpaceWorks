"""Bounded synthetic source and real disk-handle observations; no SDK patches."""

import hashlib
import io
import os
import stat
import tempfile
from types import SimpleNamespace

from botocore.response import StreamingBody

from apps.backup import storage, storage_promotion


CHUNK = 7
SIZE = 23


def synthetic(offset, size):
    return bytes((position % 251 for position in range(offset, offset + size)))


def digest_for(size):
    digest = hashlib.sha256()
    for offset in range(0, size, CHUNK):
        digest.update(synthetic(offset, min(CHUNK, size - offset)))
    return digest.hexdigest()


class NonseekableSource(io.RawIOBase):
    """Generate bytes on demand; deliberately has no usable seek implementation."""

    def __init__(self, size, *, read_error=None, close_error=False):
        super().__init__()
        self.size, self.offset = size, 0
        self.requests = []
        self.close_attempts = 0
        self.read_error, self.close_error = read_error, close_error

    def read(self, amount=-1):
        assert 0 < amount <= CHUNK
        self.requests.append((self.offset, amount))
        if self.read_error is not None and self.offset:
            raise self.read_error
        chunk = synthetic(self.offset, min(amount, self.size - self.offset))
        self.offset += len(chunk)
        return chunk

    def close(self):
        self.close_attempts += 1
        super().close()
        if self.close_error:
            raise OSError("source close failure")


class ObservedBody(StreamingBody):
    def __init__(self, raw, size):
        super().__init__(raw, size)
        self.close_attempts = 0

    def close(self):
        self.close_attempts += 1
        return super().close()


def observe_temporaries(monkeypatch, *, allocation_error=None, write_error=None,
                        close_error=False, chunk_size=CHUNK):
    """Return actual TemporaryFiles, instrumenting methods on those same handles."""
    real_temporary = tempfile.TemporaryFile
    records = []

    def allocate(*args, **kwargs):
        if allocation_error:
            raise allocation_error
        handle = real_temporary(*args, **kwargs)
        record = SimpleNamespace(handle=handle, writes=[], close_attempts=0,
                                 descriptor=handle.fileno())
        records.append(record)
        assert kwargs == {"mode": "w+b"}
        assert handle.seekable() and stat.S_ISREG(os.fstat(handle.fileno()).st_mode)
        assert stat.S_IMODE(os.fstat(handle.fileno()).st_mode) == 0o600
        assert os.fstat(handle.fileno()).st_nlink == 0
        original_write, original_close = handle.write, handle.close

        def write(chunk):
            assert isinstance(chunk, bytes) and len(chunk) <= chunk_size
            if write_error:
                raise write_error
            written = original_write(chunk)
            record.writes.append(written)
            return written

        def close():
            record.close_attempts += 1
            original_close()
            if close_error:
                raise OSError("temp close failure")

        handle.write, handle.close = write, close
        return handle

    monkeypatch.setattr(storage_promotion.tempfile, "TemporaryFile", allocate)
    monkeypatch.setattr(storage_promotion, "CHUNK_SIZE", chunk_size)
    return records


def assert_closed(body, records):
    assert body.close_attempts == 1
    assert body._raw_stream.closed
    assert body._raw_stream.close_attempts == 1
    for record in records:
        assert record.close_attempts == 1
        assert record.handle.closed
        try:
            record.handle.fileno()
        except ValueError:
            pass
        else:
            raise AssertionError("closed spool retained a usable descriptor")


class ChecksumLikeClient:
    def __init__(self, body, length, *, put_error=None):
        self.body, self.length, self.put_error = body, length, put_error
        self.gets, self.puts, self.deletes = [], [], []
        self.winner = b"existing immutable winner"

    def get_object(self, **kwargs):
        self.gets.append(kwargs)
        response = {"Body": self.body}
        if self.length != "missing":
            response["ContentLength"] = self.length
        return response

    def put_object(self, **kwargs):
        self.puts.append(kwargs)
        body = kwargs["Body"]
        assert body.seekable() and not isinstance(body, io.BytesIO)
        assert stat.S_ISREG(os.fstat(body.fileno()).st_mode)
        assert body.tell() == 0
        assert kwargs["ContentType"] == "application/octet-stream"
        assert kwargs["IfNoneMatch"] == "*"
        assert type(kwargs["ContentLength"]) is int
        for _ in range(2):  # Default-checksum shape: consume, rewind, consume again.
            digest, size = hashlib.sha256(), 0
            while chunk := body.read(CHUNK):
                assert type(chunk) is bytes
                digest.update(chunk)
                size += len(chunk)
            assert size == kwargs["ContentLength"]
            assert digest.hexdigest() == digest_for(size)
            body.seek(0)
        if self.put_error:
            raise self.put_error

    def delete_object(self, **kwargs):
        self.deletes.append(kwargs)
        raise AssertionError("promotion must never delete a remote object")


def install(monkeypatch, settings, *, size=SIZE, length=SIZE, read_error=None,
            put_error=None, allocation_error=None, write_error=None, close_error=False):
    settings.AWS_STORAGE_BUCKET_NAME = "unit-only-not-a-provider"
    raw = NonseekableSource(size, read_error=read_error, close_error=close_error)
    body = ObservedBody(raw, size)
    assert not body.seekable()
    client = ChecksumLikeClient(body, length, put_error=put_error)
    records = observe_temporaries(monkeypatch, allocation_error=allocation_error,
                                 write_error=write_error, close_error=close_error)
    monkeypatch.setattr(storage, "client", lambda: client)
    return client, body, records
