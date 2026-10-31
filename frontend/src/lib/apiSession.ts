import { API_V1_URL } from "./apiConfig";
import { readStorage, removeStorage, writeStorage } from "./safeStorage";
import { parseSessionIntent, sameSessionIntent, SessionInstallError } from "./sessionIntent";
import { invalidateSessionIntent, persistSessionIntent, readSessionIntent } from "./sessionIntentStorage";

const PUBLIC_CLIENT_ID = (import.meta.env.VITE_PUBLIC_CLIENT_ID ?? "").trim();
const ACCESS_TOKEN_KEY = "makerspace.access";
// Shared best-effort logout latch. The per-tab intent pin provides reload safety even
// when a legitimate explicit sign-in in another tab clears this shared latch.
const SIGNED_OUT_KEY = "makerspace.signed-out";
const REFRESH_CSRF_HEADER = "X-Refresh-CSRF";
let runtimePublishableKey = (import.meta.env.VITE_PUBLIC_API_KEY ?? "").trim();
let accessToken = "";
let accessRefreshPromise: Promise<boolean> | null = null;
let sessionGeneration = 0;
let signedOut = false;
let sessionIntent = readSessionIntent();
export const tenantPublishableKeys = new Map<string, string>();
// The tenant most recently bootstrapped in this session. Member and status requests
// carry no slug of their own, so without this they would send no client credential at
// all on the central /m/:slug routes -- fine today, a 401 the moment enforcement is on.
let activeTenantSlug = "";
const authExpiredListeners = new Set<() => void>();
let sessionRevision = 0;
const sessionListeners = new Set<() => void>();

export function getSessionRevision() { return sessionRevision; }
export function subscribeSession(listener: () => void) {
  sessionListeners.add(listener);
  return () => { sessionListeners.delete(listener); };
}
function publishSession() {
  sessionRevision += 1;
  sessionListeners.forEach((listener) => listener());
}

export async function publicHeaders(publishableKey?: string): Promise<HeadersInit> {
  if (PUBLIC_CLIENT_ID) {
    return { "X-Client-Id": PUBLIC_CLIENT_ID };
  }
  const key =
    publishableKey?.trim() ||
    runtimePublishableKey ||
    tenantPublishableKeys.get(activeTenantSlug) ||
    "";
  return key ? { "X-Publishable-Key": key } : {};
}

export function setRuntimePublishableKey(key: string) {
  runtimePublishableKey = key.trim();
}

export function cacheTenantPublishableKey(slug: string, key: string) {
  const normalized = slug.trim();
  const normalizedKey = key.trim();
  if (normalized && normalizedKey) {
    tenantPublishableKeys.set(normalized, normalizedKey);
    activeTenantSlug = normalized;
  }
}

export function getAccessToken() {
  return accessToken;
}

export function getSessionGeneration() {
  return sessionGeneration;
}

export function cleanupLegacyAccessToken() {
  removeStorage(ACCESS_TOKEN_KEY);
}

export function authHeaders(): HeadersInit {
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {};
}

export function addAuthExpiredListener(listener: () => void) {
  authExpiredListeners.add(listener);
  return () => {
    authExpiredListeners.delete(listener);
  };
}

export function expireStaffAuthSession() {
  clearAccessToken();
  authExpiredListeners.forEach((listener) => listener());
}

export function canRefreshAfterUnauthorized(path: string) {
  return !["/auth/login", "/auth/refresh", "/auth/logout"].includes(path);
}

export function setAccessToken(token: string) {
  const intent = parseSessionIntent(token);
  if (!intent) throw new SessionInstallError("invalid_token");
  persistSessionIntent(intent);
  invalidatePendingRefresh();
  sessionIntent = intent;
  accessToken = token;
  signedOut = false;
  removeStorage(SIGNED_OUT_KEY);
  cleanupLegacyAccessToken();
  publishSession();
}

export function clearAccessToken() {
  clearLocalSessionState();
  publishSession();
}

function clearLocalSessionState() {
  invalidatePendingRefresh();
  accessToken = "";
  cleanupLegacyAccessToken();
}

function invalidatePendingRefresh() {
  // Old async work must not write into a newer login or a locally cleared session.
  sessionGeneration += 1;
  accessRefreshPromise = null;
}

export async function refreshAccessToken(): Promise<boolean> {
  const intent = sessionIntent;
  if (!intent || signedOut || readStorage(SIGNED_OUT_KEY)) return false;
  if (!accessRefreshPromise) {
    const generation = sessionGeneration;
    const refreshPromise = (async () => {
      const response = await fetch(`${API_V1_URL}/auth/refresh`, {
        method: "POST",
        credentials: "include",
        headers: {
          [REFRESH_CSRF_HEADER]: "1",
        },
      }).catch(() => null);

      if (!response?.ok) {
        return false;
      }

      const body: unknown = await response.json().catch(() => null);
      const token = body !== null && typeof body === "object" && "access" in body ? body.access : null;
      const refreshedIntent = parseSessionIntent(token);
      if (typeof token !== "string" || !refreshedIntent || !sameSessionIntent(intent, refreshedIntent)
        || generation !== sessionGeneration || sessionIntent !== intent
        || signedOut || readStorage(SIGNED_OUT_KEY)) {
        return false;
      }

      // A refresh continues this generation; only explicit sign-in may lift the latch.
      accessToken = token;
      cleanupLegacyAccessToken();
      publishSession();
      return true;
    })().finally(() => {
      // A newer session may already have started its own refresh.
      if (accessRefreshPromise === refreshPromise) accessRefreshPromise = null;
    });
    accessRefreshPromise = refreshPromise;
  }

  return accessRefreshPromise;
}

export class LogoutIncompleteError extends Error {
  constructor(readonly reason: "server_unconfirmed" | "storage_unavailable" | "server_and_storage_unconfirmed" = "server_unconfirmed") {
    super(reason === "server_unconfirmed"
      ? "You are signed out in this tab, but the server did not confirm it. This tab will not sign back in on its own."
      : reason === "storage_unavailable"
        ? "You are signed out in this tab, but this browser could not save the sign-out. Sign-out after reloading cannot be guaranteed."
        : "You are signed out in this tab, but neither the server nor this browser's storage confirmed the sign-out. Sign-out after reloading cannot be guaranteed.");
    this.name = "LogoutIncompleteError";
  }
}

/**
 * Drops the local session and latches refresh off before contacting the server. Completion
 * never changes local state: an explicit sign-in may have happened while logout was pending.
 * Server failure or unproven per-tab pin invalidation throws LogoutIncompleteError.
 */
export async function logout(): Promise<void> {
  signedOut = true;
  sessionIntent = null;
  writeStorage(SIGNED_OUT_KEY, "1");
  clearLocalSessionState();
  const durable = invalidateSessionIntent();
  publishSession();
  const response = await fetch(`${API_V1_URL}/auth/logout`, {
    method: "POST",
    credentials: "include",
    headers: {
      [REFRESH_CSRF_HEADER]: "1",
    },
  }).catch(() => null);
  if (!response?.ok || !durable) {
    throw new LogoutIncompleteError(durable ? "server_unconfirmed"
      : response?.ok ? "storage_unavailable" : "server_and_storage_unconfirmed");
  }
}
