"""SDK transport retaining real data-version and delete-marker distinctions."""
from tests.document_safety.helpers import DocumentStore


class VersionStore(DocumentStore):
    def __init__(self, *, page_size=1000):
        super().__init__()
        self.markers = {}
        self.page_size = page_size
        self.delete_responses = []

    def mark_deleted(self, key):
        with self.lock:
            self.serial += 1
            version = str(self.serial)
            self.markers.setdefault(key, set()).add(version)
            self.objects.pop(key, None)
            return version

    def list_object_versions(self, **kwargs):
        self._call("list", kwargs)
        with self.lock:
            rows = [(key, version, "Versions") for key, versions in self.versions.items()
                    if key.startswith(kwargs["Prefix"]) for version in versions]
            rows += [(key, version, "DeleteMarkers") for key, versions in self.markers.items()
                     if key.startswith(kwargs["Prefix"]) for version in versions]
            rows.sort()
            if "KeyMarker" in kwargs:
                marker = (kwargs["KeyMarker"], kwargs["VersionIdMarker"])
                rows = [row for row in rows if row[:2] > marker]
            selected = rows[:self.page_size]
            more = len(rows) > len(selected)
            result = {"IsTruncated": more, "Versions": [], "DeleteMarkers": []}
            for key, version, group in selected:
                result[group].append({"Key": key, "VersionId": version})
            if more:
                result.update(NextKeyMarker=selected[-1][0], NextVersionIdMarker=selected[-1][1])
            return result

    def delete_objects(self, **kwargs):
        response = self.delete_responses.pop(0) if self.delete_responses else {}
        if response is None or response is False or (isinstance(response, dict) and response.get("Errors")):
            self._call("delete", kwargs)
            return response
        result = super().delete_objects(**kwargs)
        with self.lock:
            for row in kwargs["Delete"]["Objects"]:
                self.markers.get(row["Key"], set()).discard(row["VersionId"])
        return result
