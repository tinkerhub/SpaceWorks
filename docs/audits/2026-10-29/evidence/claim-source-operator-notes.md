# Claim transition source admission — operator wording

For the 0.9.0 upgrade notes:

Converting a walk-in record into an account is temporarily blocked when any linked makerspace is frozen, including links through inactive or revoked memberships. Rare multi-makerspace attempts from a dedicated origin may require retrying from the central origin to preserve lock order. Native password changes show a retry message; an OIDC callback receives the typed source-gate refusal. Credentials and claim-created presence change together or remain unchanged.

Rejected claim tokens still return the generic authentication failure. Defensive cleanup of inconsistent legacy presence waits for its actual makerspace to become writable; deferring cleanup never restores token access. Normal claim revocation already ends the matching presence in its original transaction, and normal presence expiry is bounded by the claim deadline.

Source map insertion for Accounts:

`accounts/claim_transition_gate.py` pins a walk-in identity's complete membership makerspace set, admits source namespaces in order before identity row locks, and refuses scope growth rather than acquiring new namespaces under row locks. The native password and bound OIDC adapters retain this admission through their real transition commits.

These notes describe the final approved source contract. Root runtime, final guard binding and release QA remain pending; this document is not a production-ready certification.
