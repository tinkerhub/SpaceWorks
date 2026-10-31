"""Versioned fake S3 used only by the atomic-publication contract tests."""
from io import BytesIO
from threading import RLock

from botocore.exceptions import ClientError
from PIL import Image


def error(code="NoSuchKey", status=404):
    return ClientError({"Error": {"Code": code},
                        "ResponseMetadata": {"HTTPStatusCode": status}}, "FakeS3")


def png(color="blue"):
    stream = BytesIO()
    Image.new("RGB", (3, 3), color).save(stream, format="PNG")
    return stream.getvalue()


class Store:
    def __init__(self, *, boundary=None):
        self.objects, self.versions = {}, {}
        self.calls, self.streams, self.put_bodies = [], [], []
        self.before_get = self.before_put = self.before_delete = None
        self.boundary = boundary
        self.lock = RLock()
        self.serial = 0

    def seed(self, key, data, mime="application/pdf"):
        with self.lock:
            self.serial += 1
            version = str(self.serial)
            self.objects[key] = (data, mime, version)
            self.versions.setdefault(key, {})[version] = (data, mime)
            return version

    def _call(self, name, kwargs):
        if self.boundary:
            self.boundary()
        self.calls.append((name, kwargs.copy()))

    def get_object(self, **kwargs):
        self._call("get", kwargs)
        if self.before_get:
            self.before_get(kwargs)
        with self.lock:
            key = kwargs["Key"]
            if key not in self.objects:
                raise error()
            data, mime, version = self.objects[key]
            body = BytesIO(data)
            self.streams.append(body)
            # Deliberately false HEAD-like metadata: observed GET bytes are authority.
            return {"Body": body, "ContentType": mime, "ContentLength": 1,
                    "Metadata": {"origin": "same-get"}, "VersionId": version}

    def put_object(self, **kwargs):
        self._call("put", kwargs)
        self.put_bodies.append(kwargs["Body"])
        assert kwargs["IfNoneMatch"] == "*", "No unconditional publication"
        if self.before_put:
            self.before_put(kwargs)
        with self.lock:
            if kwargs["Key"] in self.objects:
                raise error("PreconditionFailed", 412)
            data = kwargs["Body"].read()
            self.seed(kwargs["Key"], data, kwargs["ContentType"])
        return {}

    def head_object(self, **kwargs):
        self._call("head", kwargs)
        with self.lock:
            if kwargs["Key"] not in self.objects:
                raise error()
            data, mime, _version = self.objects[kwargs["Key"]]
            return {"ContentLength": len(data), "ContentType": mime}

    def get_bucket_versioning(self, **kwargs):
        self._call("versioning", kwargs)
        return {"Status": "Enabled"}

    def list_object_versions(self, **kwargs):
        self._call("list", kwargs)
        with self.lock:
            return {"IsTruncated": False, "Versions": [
                {"Key": key, "VersionId": version}
                for key, versions in self.versions.items()
                if key.startswith(kwargs["Prefix"]) for version in versions
            ]}

    def delete_objects(self, **kwargs):
        self._call("delete", kwargs)
        if self.before_delete:
            self.before_delete(kwargs)
        with self.lock:
            for item in kwargs["Delete"]["Objects"]:
                key, version = item["Key"], item["VersionId"]
                self.versions.get(key, {}).pop(version, None)
                if key in self.objects and self.objects[key][2] == version:
                    remaining = self.versions.get(key, {})
                    if remaining:
                        latest = next(reversed(remaining))
                        data, mime = remaining[latest]
                        self.objects[key] = (data, mime, latest)
                    else:
                        self.objects.pop(key, None)
        return {}

    def delete_object(self, **kwargs):
        raise AssertionError("Ordinary cleanup must never issue bare DeleteObject")

    def copy_object(self, **kwargs):
        raise AssertionError("Conditional publication must never fall back to COPY")
