"""Version-one positive full grammars, including deleted historical contexts."""

import re
import uuid
import json

from .purge_storage import PurgeStorageRefused, bucket_name, list_versions
from .purge_object_closure import _safe_key

IMAGES = ["jpg", "jpeg", "png", "webp"]
RECEIPTS = IMAGES + ["pdf"]
DOCUMENTS = RECEIPTS + ["stl", "3mf", "step", "stp", "obj", "amf", "ply", "gcode", "gco", "iges", "igs", "dxf"]
VOCABULARY = {"images": IMAGES, "receipts": RECEIPTS, "documents": DOCUMENTS}
ROOTS = {
    "events": [("public_image", "event"), ("public_image", "event-series"), ("private", "event-certificates")],
    "membership": [("public_image", "member")],
    "bookings": [("public_image", "spaces")],
    "maintenance": [("private", "machines")],
    "procurement": [("private", "procurement")],
    "machine_service": [("private", "machine")],
}
H = r"[0-9a-f]{32}"
N = r"[1-9][0-9]{0,18}"
U = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


def clauses(module, maker_id):
    return {"version": 1, "module": module, "maker": maker_id, "vocabulary": VOCABULARY}


def validate_clauses(value, module, maker_id):
    # Equality freezes the old vocabulary even if future builders allow more types.
    try:
        known = json.dumps(value, sort_keys=True) == json.dumps(clauses(module, maker_id), sort_keys=True)
    except (TypeError, ValueError):
        known = False
    if not known:
        raise PurgeStorageRefused("Unknown module cleanup grammar or vocabulary.")


def listing_prefixes(value):
    for kind, root in ROOTS.get(value["module"], []):
        prefix = f"{root}/{value['maker']}/"
        yield kind, prefix
        yield kind, f"staging/{prefix}"


def owns_key(value, kind, key):
    _safe_key(key)
    final = key.removeprefix("staging/")
    maker, module = value["maker"], value["module"]
    e = "(?:" + "|".join(IMAGES) + ")"
    r = "(?:" + "|".join(RECEIPTS) + ")"
    d = "(?:" + "|".join(DOCUMENTS) + ")"
    patterns = {
        "events": [("public_image", rf"(?:event|event-series)/{maker}/{H}\.{e}"),
                   ("private", rf"event-certificates/{maker}/{U}\.pdf")],
        "membership": [("public_image", rf"member/{maker}/{H}\.{e}")],
        "bookings": [("public_image", rf"spaces/{maker}/{N}/images/{H}\.{e}")],
        "maintenance": [("private", rf"machines/{maker}/{N}/logs/{H}\.{d}")],
        "procurement": [("private", rf"procurement/{maker}/{N}/receipts/{H}\.{r}")],
        "machine_service": [("private", rf"machine/{maker}/(?:{N}|queue-{N})/service/{H}")],
    }
    if not any(kind == k and re.fullmatch(pattern, final) for k, pattern in patterns.get(module, [])):
        return False
    parts = final.split("/")
    if module in {"bookings", "maintenance", "procurement", "machine_service"}:
        if int(parts[2].removeprefix("queue-")) > 9223372036854775807:
            return False
    if parts[0] == "event-certificates":
        return str(uuid.UUID(parts[2][:-4])) == parts[2][:-4]
    return True


def own_branch(value, kind, key):
    """Known sibling structures under shared roots remain outside authority."""
    final = key.removeprefix("staging/")
    for k, root in ROOTS.get(value["module"], []):
        prefix = f"{root}/{value['maker']}/"
        if k != kind or not final.startswith(prefix):
            continue
        suffix = final[len(prefix):]
        if root == "machines":
            return bool(re.match(r"[^/]+/logs(?:/|$)", suffix))
        if root == "machine":
            return bool(re.match(r"[^/]+/service(?:/|$)", suffix))
        return True
    return False


def enumerate_closure(receipt, s3, verify):
    result = {tuple(pair) for pair in receipt.exact_keys}
    for kind, prefix in listing_prefixes(receipt.namespace_clauses):
        verify()
        for row in list_versions(s3, bucket_name(kind), prefix):
            key = row["Key"]
            # Immutable typed holder authority also covers legacy names inside a
            # known root. Unknown rowless names still require the full grammar.
            if (kind, key) in result or owns_key(receipt.namespace_clauses, kind, key):
                result.add((kind, key))
            elif own_branch(receipt.namespace_clauses, kind, key):
                raise PurgeStorageRefused("Malformed object in the module's own namespace; cleanup refused.")
            if len(result) > 100000:
                raise PurgeStorageRefused("Module cleanup closure exceeds the bounded limit.")
    return result
