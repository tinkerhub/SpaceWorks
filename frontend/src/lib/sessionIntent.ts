type Surface = "member" | "staff" | "staff_api" | "verification_only";
type Identity = { version: 1; user_id: string; auth_generation: string };

/** An identity comparison hint only. The API still verifies every bearer token. */
export type SessionIntent = Readonly<Identity & (
  | { token_type: "access"; surface: Exclude<Surface, "staff"> }
  | { token_type: "access"; surface: "staff"; staff_scope: string }
  | {
    token_type: "claim_access"; surface: "member"; claim_session_id: string;
    claim_membership_id: string; claim_makerspace_id: string;
  }
)>;

export class SessionInstallError extends Error {
  readonly code = "session_install_failed";

  constructor(readonly reason: "invalid_token" | "storage_unavailable") {
    super(reason === "invalid_token"
      ? "The sign-in response did not contain a supported browser session. Please sign in again."
      : "This browser could not safely save the new sign-in. Please enable session storage and try again.");
    this.name = "SessionInstallError";
  }
}

const MAX_TOKEN_BYTES = 16_384;
const MAX_PAYLOAD_ENCODED_BYTES = 8_192;
const MAX_PAYLOAD_BYTES = 6_144;
const MAX_PIN_BYTES = 1_024;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const CLAIM_KEYS = ["claim_session_id", "claim_membership_id", "claim_makerspace_id"];

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function positiveId(value: unknown): string | null {
  if (typeof value === "number") {
    return Number.isSafeInteger(value) && value > 0 ? String(value) : null;
  }
  if (typeof value !== "string" || !/^[1-9][0-9]{0,15}$/.test(value)) return null;
  const number = Number(value);
  return Number.isSafeInteger(number) && String(number) === value ? value : null;
}

function uuid(value: unknown): string | null {
  return typeof value === "string" && UUID.test(value) ? value.toLowerCase() : null;
}

function identityFromClaims(value: unknown): SessionIntent | null {
  if (!object(value) || "device_grant_id" in value || "device_family_id" in value) return null;
  const user_id = positiveId(value.user_id);
  const auth_generation = uuid(value.auth_generation);
  if (!user_id || !auth_generation) return null;
  const identity: Identity = { version: 1, user_id, auth_generation };
  const surface = value.surface;
  if (surface !== "member" && surface !== "staff" && surface !== "staff_api"
    && surface !== "verification_only") return null;

  if (value.token_type === "claim_access") {
    const claim_session_id = uuid(value.claim_session_id);
    const claim_membership_id = positiveId(value.claim_membership_id);
    const claim_makerspace_id = positiveId(value.claim_makerspace_id);
    if (surface !== "member" || "staff_scope" in value
      || !claim_session_id || !claim_membership_id || !claim_makerspace_id) return null;
    return Object.freeze({
      ...identity, token_type: "claim_access", surface, claim_session_id,
      claim_membership_id, claim_makerspace_id,
    });
  }

  if (value.token_type !== "access" || CLAIM_KEYS.some((key) => key in value)
    || "absolute_expires_at" in value) return null;
  if (surface === "staff") {
    const scope = value.staff_scope;
    if (typeof scope !== "string" || (scope !== "platform" && !positiveId(scope))) return null;
    return Object.freeze({ ...identity, token_type: "access", surface, staff_scope: scope });
  }
  if ("staff_scope" in value) return null;
  return Object.freeze({ ...identity, token_type: "access", surface });
}

/** Bounded compact-JWT decoding, without claiming to verify its signature or authority. */
export function parseSessionIntent(token: unknown): SessionIntent | null {
  if (typeof token !== "string" || token.length > MAX_TOKEN_BYTES) return null;
  const parts = token.split(".");
  if (parts.length !== 3 || parts.some((part) => !/^[A-Za-z0-9_-]+$/.test(part) || part.length % 4 === 1)) {
    return null;
  }
  const payload = parts[1];
  if (payload.length > MAX_PAYLOAD_ENCODED_BYTES) return null;
  try {
    const decoded = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    if (decoded.length > MAX_PAYLOAD_BYTES
      || btoa(decoded).replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_") !== payload) return null;
    const bytes = Uint8Array.from(decoded, (char) => char.charCodeAt(0));
    return identityFromClaims(JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)));
  } catch {
    return null;
  }
}

/** Stored pins admit only the versioned, canonical identity fields, with no extra data. */
export function parseStoredSessionIntent(raw: unknown): SessionIntent | null {
  if (typeof raw !== "string" || raw.length > MAX_PIN_BYTES) return null;
  try {
    const value: unknown = JSON.parse(raw);
    const intent = identityFromClaims(value);
    if (!object(value) || !intent || value.version !== 1
      || Object.keys(value).length !== Object.keys(intent).length
      || !Object.entries(intent).every(([key, entry]) => value[key] === entry)) return null;
    return intent;
  } catch {
    return null;
  }
}

export function sameSessionIntent(left: SessionIntent, right: SessionIntent): boolean {
  // Both operands come from the canonical constructors above, including field order.
  return JSON.stringify(left) === JSON.stringify(right);
}
