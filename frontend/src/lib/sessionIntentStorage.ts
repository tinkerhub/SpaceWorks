import {
  parseStoredSessionIntent, SessionInstallError, type SessionIntent,
} from "./sessionIntent";

export const SESSION_INTENT_KEY = "makerspace.session-intent";
// Deliberately outside the pin schema: reloading this value can never authorize refresh.
const INVALIDATED_PIN = '{"version":1,"invalidated":true}';

export function readSessionIntent(): SessionIntent | null {
  try {
    return parseStoredSessionIntent(window.sessionStorage.getItem(SESSION_INTENT_KEY));
  } catch {
    return null;
  }
}

function writeVerified(value: string): boolean {
  try {
    window.sessionStorage.setItem(SESSION_INTENT_KEY, value);
  } catch {
    // A read-back is still needed: a throwing write is not proof of the stored value.
  }
  try {
    return window.sessionStorage.getItem(SESSION_INTENT_KEY) === value;
  } catch {
    return false;
  }
}

function isInvalidated(): boolean {
  try {
    const value = window.sessionStorage.getItem(SESSION_INTENT_KEY);
    return value === null || value === INVALIDATED_PIN;
  } catch {
    return false;
  }
}

/** Returns proof of per-tab reload safety, independently of the shared logout latch. */
export function invalidateSessionIntent(): boolean {
  try {
    window.sessionStorage.removeItem(SESSION_INTENT_KEY);
  } catch {
    // A failed removal may still be recoverable with an invalid marker.
  }
  return isInvalidated() || writeVerified(INVALIDATED_PIN);
}

/** Complete storage work before the caller changes any in-memory session state. */
export function persistSessionIntent(intent: SessionIntent): void {
  if (writeVerified(JSON.stringify(intent))) return;
  // Memory-only sign-in is safe only when an older persistent identity cannot revive.
  if (!invalidateSessionIntent()) throw new SessionInstallError("storage_unavailable");
}
