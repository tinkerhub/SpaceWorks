import { accessToken } from "../test/accessTokens";
import { afterAll, afterEach, beforeEach, expect, vi } from "vitest";

// apiSession reads these once at import. Keep credentials deterministic even on
// machines with a local Vite environment; use the real session module throughout.
vi.hoisted(() => {
  vi.stubEnv("VITE_PUBLIC_CLIENT_ID", "");
  vi.stubEnv("VITE_PUBLIC_API_KEY", "");
  vi.stubEnv("VITE_API_URL", "http://localhost:8000/api");
});

import { StructuredApiError } from "./apiErrors";
import {
  apiGet, fetchJson, memberRequest,
  memberRequestBlob, publicV1Request, staffRequest, staffRequestBlob,
  tenantPublicRequest, tenantPublicRequestBlob,
} from "./apiRequests";
import {
  addAuthExpiredListener, clearAccessToken, getAccessToken, logout, setAccessToken,
} from "./apiSession";
import {
  deferred, fetchMock, jsonResponse, resetSessionTransport,
} from "./apiSessionTestHelpers";

export const publicationCases = [
  { name: "fetchJson", request: () => fetchJson("/api/public/tools"), kind: "json", structured: false, retry: false, tenant: false },
  { name: "apiGet", request: () => apiGet("/public/tools"), kind: "json", structured: false, retry: false, tenant: false },
  { name: "public V1", request: () => publicV1Request("/public/forge/tools"), kind: "json", structured: true, retry: false, tenant: false },
  { name: "staff JSON", request: () => staffRequest("/admin/tools"), kind: "json", structured: true, retry: true, tenant: false },
  { name: "member JSON", request: () => memberRequest("/member/profile"), kind: "json", structured: true, retry: true, tenant: false },
  { name: "tenant JSON", request: () => tenantPublicRequest("forge", "/public/forge/tools"), kind: "json", structured: true, retry: true, tenant: true },
  { name: "staff blob", request: () => staffRequestBlob("/admin/export"), kind: "blob", structured: true, retry: true, tenant: false },
  { name: "member blob", request: () => memberRequestBlob("/member/calendar"), kind: "blob", structured: true, retry: true, tenant: false },
  { name: "tenant blob", request: () => tenantPublicRequestBlob("forge", "/public/forge/calendar"), kind: "blob", structured: true, retry: true, tenant: true },
] as const;

export const sessionChanges = [
  { name: "logout", token: "", logout: true, change: async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(204));
    await logout();
  } },
  { name: "clear", token: "", logout: false, change: async () => { clearAccessToken(); } },
  { name: "same-token login", token: accessToken("old-access"), logout: false, change: async () => { setAccessToken(accessToken("old-access")); } },
  { name: "different-token login", token: accessToken("account-B", { user_id: 2 }), logout: false, change: async () => { setAccessToken(accessToken("account-B", { user_id: 2 })); } },
] as const;

export function publicationSetup() {
  const expired = vi.fn();
  let unsubscribe: () => void;
  beforeEach(() => {
    resetSessionTransport();
    expired.mockReset();
    unsubscribe = addAuthExpiredListener(expired);
  });
  afterEach(() => {
    unsubscribe();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });
  afterAll(() => { vi.unstubAllEnvs(); });
  return expired;
}

export const oldData = { owner: "account-A", private: "obsolete data" };
export function successfulValue(kind: "json" | "blob") {
  return kind === "blob" ? new Blob(["account-A private bytes"], { type: "text/plain" }) : oldData;
}

/** The entered signal proves fetch already returned and the real wrapper is
 * awaiting body decoding. A post-fetch check alone cannot satisfy these cases. */
export function heldBody(status: number, kind: "json" | "blob" = "json") {
  const response = jsonResponse(status);
  const entered = deferred<void>();
  const result = deferred<unknown>();
  const decode = vi.fn(async () => {
    entered.resolve();
    const value = await result.promise;
    if (value instanceof Error) throw value;
    return value;
  });
  if (kind === "blob") {
    vi.spyOn(response, "blob").mockImplementation(async () => await decode() as Blob);
  } else {
    vi.spyOn(response, "json").mockImplementation(decode);
  }
  return { response, entered: entered.promise, resolve: result.resolve, decode };
}

// Attach this before releasing a held response, so even immediate rejection is
// observed. Exact error-body equality also excludes the old account's payload.
export async function expectSessionChanged(request: Promise<unknown>) {
  const error: unknown = await request.then(
    () => { throw new Error("Obsolete response was published"); },
    (reason: unknown) => reason,
  );
  expect(error).toBeInstanceOf(StructuredApiError);
  expect(error).toMatchObject({ status: 401, code: "session_changed" });
  expect((error as StructuredApiError).body).toEqual({
    code: "session_changed", detail: expect.any(String),
  });
}

export function expectUnchangedCredentials(token: string, expired: ReturnType<typeof vi.fn>, calls: number) {
  expect(getAccessToken()).toBe(token);
  expect(expired).not.toHaveBeenCalled();
  expect(fetchMock).toHaveBeenCalledTimes(calls);
}
