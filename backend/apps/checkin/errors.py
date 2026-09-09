"""Machine-readable refusals shared by check-in workflows."""

from rest_framework.exceptions import PermissionDenied


def denied(code: str, detail: str) -> PermissionDenied:
    """Build a DRF refusal whose response preserves the check-in reason code."""
    exc = PermissionDenied(detail)
    exc.detail = {"detail": detail, "code": code}
    return exc
