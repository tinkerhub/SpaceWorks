"""In-memory S3 transport; production upload/readback/conditional-final code runs."""

from io import BytesIO

from botocore.exceptions import ClientError
from django.db import connection

from apps.backup import storage


class Store:
    def __init__(self):
        self.objects = {}
        self.events = []
        self.fail_at = None
        self.cleanup_ok = True

    def event(self, operation, key):
        # The test owns no surrounding transaction. Thus any atomic block here
        # belongs to production code and would put remote work under DB locks.
        assert not connection.in_atomic_block, (operation, key)
        self.events.append((operation, key))
        if operation == self.fail_at:
            raise OSError("simulated remote transport interruption")

    def upload_fileobj(self, body, _bucket, key, **_kwargs):
        self.event("upload", key)
        self.objects[key] = body.read()

    def get_object(self, *, Bucket, Key):
        self.event("get-final" if "/deployment/" in Key else "get-staging", Key)
        return {"Body": BytesIO(self.objects[Key])}

    def put_object(self, *, Bucket, Key, Body, IfNoneMatch, **_kwargs):
        self.event("create-final", Key)
        assert IfNoneMatch == "*"
        if Key in self.objects:
            raise ClientError({"Error": {"Code": "PreconditionFailed"},
                               "ResponseMetadata": {"HTTPStatusCode": 412}}, "PutObject")
        self.objects[Key] = Body.read()

    def head_object(self, *, Bucket, Key):
        self.event("head", Key)
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "HeadObject")
        return {"ContentLength": len(self.objects[Key])}

    def delete(self, key):
        self.event("delete", key)
        if self.cleanup_ok:
            self.objects.pop(key, None)
        return self.cleanup_ok

    def delete_prefix(self, prefix):
        for key in tuple(self.objects):
            if key.startswith(prefix):
                self.delete(key)
        return self.cleanup_ok


def install_store(monkeypatch):
    store = Store()
    monkeypatch.setattr(storage, "client", lambda **_kwargs: store)
    monkeypatch.setattr(storage, "delete_archive", store.delete)
    monkeypatch.setattr(storage, "delete_archive_prefix", store.delete_prefix)
    return store
