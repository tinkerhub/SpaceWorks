"""Renew the caller's browser session after global credential revocation."""

from apps.accounts.tokens import SpaceWorksRefreshToken
from apps.backup.recovery import assert_token_issuance_allowed


def reissue_browser_session(request, user) -> SpaceWorksRefreshToken | None:
    if request.auth is None or "device_grant_id" in request.auth:
        return None
    assert_token_issuance_allowed(user)
    refresh = SpaceWorksRefreshToken.for_user(user)
    surface = request.auth.get("surface")
    if surface is not None:
        refresh["surface"] = surface
    if surface == "staff":
        refresh["staff_scope"] = request.auth.get("staff_scope")
    return refresh
