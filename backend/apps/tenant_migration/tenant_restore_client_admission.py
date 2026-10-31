"""Explicit optional API-client request admission from authenticated artifact facts."""

from dataclasses import dataclass

from .tenant_client_catalog import _digest
from .tenant_restore_api_clients import parse_approvals
from .tenant_restore_artifact_admission import freeze, thaw
from .tenant_restore_types import TenantRestoreRefused, ValidatedApiClientTargetAdapter


@dataclass(frozen=True, slots=True)
class ValidatedClientRequest:
    requested: bool
    approved_records: tuple
    source_catalog_sha256: str | None
    approval_records_sha256: str | None

    def ledger_bindings(self):
        return {"api_client_reissue_requested": self.requested,
                "api_client_catalog_sha256": self.source_catalog_sha256,
                "api_client_approvals_sha256": self.approval_records_sha256}


def validate_client_request(inputs, context, target):
    document = inputs.api_client_approvals
    if document is None:
        records = []
    elif (not isinstance(document, dict) or set(document) not in ({"approvals"}, {"version", "approvals"})
          or ("version" in document and (type(document["version"]) is not int or document["version"] != 1))
          or not isinstance(document.get("approvals"), list)):
        raise TenantRestoreRefused("The API-client approval file is malformed.")
    else:
        records = document["approvals"]
    catalog_sha = context.api_client_catalog["sha256"] if context.api_client_catalog is not None else None
    if not records:
        return ValidatedClientRequest(False, (), catalog_sha, None)
    if context.outer_version != 2 or context.api_client_catalog is None:
        raise TenantRestoreRefused("API-client reissue requires an authenticated v2 source catalog.")
    reissuer = getattr(target, "reissue_validated_api_clients", None)
    if (not callable(reissuer) or getattr(reissuer, "__func__", None)
            is ValidatedApiClientTargetAdapter.reissue_validated_api_clients):
        raise TenantRestoreRefused("The target adapter does not support validated API-client reissue.")
    approved = parse_approvals(document, artifact_sha256=context.artifact_sha256,
                               capture_id=context.capture_id, catalog=thaw(context.api_client_catalog))
    return ValidatedClientRequest(True, tuple(freeze(record) for record in approved),
                                  catalog_sha, _digest(list(approved)))


def reissue_validated_request(target, sibling, inputs, request, bindings):
    if not request.requested:
        return {"artifact_bindings": bindings, "reissued": 0, "status": "not_requested"}
    # Trusted provider bridge runs reissue_approved_client in its isolated sibling
    # process with CredentialDeliveryStore. Never journal the provider's return value.
    target.reissue_validated_api_clients(
        sibling, inputs, approved_records=request.approved_records,
        source_catalog_sha256=request.source_catalog_sha256,
        approval_records_sha256=request.approval_records_sha256,
    )
    return {"artifact_bindings": bindings, "status": "completed",
            "approved_records": len(request.approved_records)}
