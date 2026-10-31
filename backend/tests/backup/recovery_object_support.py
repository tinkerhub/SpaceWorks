"""Synthetic S3 wire implementation with bytes, headers, history and stream closure."""

from copy import deepcopy
from io import BytesIO
import hashlib

from botocore.exceptions import ClientError


class ObjectWire:
    def __init__(self):
        self.objects, self.versions, self.events, self.streams = {}, {}, [], []

    def put(self, key, payload, **facts):
        self.objects[key] = {"payload": payload, "Metadata": {"purpose": "recovery"},
            "ContentType": "application/octet-stream", "CacheControl": "private", **facts}

    def head_object(self, *, Bucket, Key):
        self.events.append(("head", Key))
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}, "ResponseMetadata": {"HTTPStatusCode": 404}}, "HeadObject")
        obj = self.objects[Key]
        return {k: v for k, v in obj.items() if k != "payload"} | {"ContentLength": len(obj["payload"])}

    def get_object(self, *, Bucket, Key):
        self.events.append(("get", Key))
        facts = self.head_object(Bucket=Bucket, Key=Key)
        body = BytesIO(self.objects[Key]["payload"])
        self.streams.append(body)
        return {**facts, "Body": body}

    def get_bucket_versioning(self, **_kwargs):
        # Real fallback to quiesced storage after provider capability refusal.
        raise ClientError({"Error": {"Code": "AccessDenied"}}, "GetBucketVersioning")

    def copy_object(self, *, Bucket, Key, CopySource, MetadataDirective):
        self.events.append(("copy", Key))
        assert MetadataDirective == "COPY"
        self.objects[Key] = deepcopy(self.objects[CopySource["Key"]])
        return {}

    def upload_fileobj(self, stream, bucket, key, *, ExtraArgs):
        self.events.append(("upload", key))
        self.put(key, stream.read(), **ExtraArgs)

    def list_object_versions(self, *, Bucket, Prefix, **kwargs):
        self.events.append(("versions", Prefix))
        return {"Versions": [{"Key": Prefix, "VersionId": value} for value in self.versions.get(Prefix, ())],
            "IsTruncated": False}


def object_fact(key, payload):
    return {"bucket_kind": "private", "key": key, "makerspace_id": None, "module_key": "",
        "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
        "metadata": {"purpose": "recovery"}, "content_type": "application/octet-stream",
        "headers": {"CacheControl": "private"}, "version_id": None}
