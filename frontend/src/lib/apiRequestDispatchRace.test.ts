import { accessToken } from "../test/accessTokens";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StructuredApiError } from "./apiErrors";
import {
  memberRequest, memberRequestBlob, publicV1Request,
  tenantPublicRequest, tenantPublicRequestBlob,
} from "./apiRequests";
import {
  addAuthExpiredListener, clearAccessToken, getAccessToken, getSessionGeneration,
  logout, setAccessToken,
} from "./apiSession";
import { fetchMock, jsonResponse, requestHeaders, resetSessionTransport } from "./apiSessionTestHelpers";

const mutation = { method: "POST", body: JSON.stringify({ action: "old-session-action" }) };
const requests = [
  { name: "member JSON", request: () => memberRequest("/member/profile", mutation) },
  { name: "member blob", request: () => memberRequestBlob("/member/calendar") },
  { name: "tenant public JSON", request: () => tenantPublicRequest("forge", "/public/forge/requests", mutation) },
  { name: "tenant public blob", request: () => tenantPublicRequestBlob("forge", "/public/forge/calendar") },
  { name: "public V1 JSON", request: () => publicV1Request("/public/forge/requests", mutation) },
];
const transitions = [
  { name: "new-account login", change: () => setAccessToken(accessToken("new-user", { user_id: 2 })), token: accessToken("new-user", { user_id: 2 }) },
  { name: "same-token explicit login", change: () => setAccessToken(accessToken("old-access")), token: accessToken("old-access") },
  { name: "clear", change: clearAccessToken, token: "" },
  { name: "logout", change: logout, token: "" },
];
const expired = vi.fn();
let unsubscribe: () => void;

beforeEach(() => {
  // Warm the tenant key and reset runtime credentials so only publicHeaders yields.
  resetSessionTransport();
  fetchMock.mockImplementation(async () => jsonResponse(200, { result: "unexpected dispatch" }));
  expired.mockReset();
  unsubscribe = addAuthExpiredListener(expired);
});
afterEach(() => { unsubscribe(); vi.unstubAllGlobals(); });

describe.each(requests)("$name pre-initial-dispatch generation guard", ({ request }) => {
  it.each(transitions)("rejects before initial dispatch after $name", async ({ name, change, token }) => {
    const generation = getSessionGeneration();
    const operation = request();
    expect(fetchMock).not.toHaveBeenCalled();
    // No await here: change the session before the real publicHeaders await resumes.
    const transition = change();

    await expect(operation).rejects.toBeInstanceOf(StructuredApiError);
    await expect(operation).rejects.toMatchObject({ status: 401, code: "session_changed" });
    await transition;

    expect(getSessionGeneration()).toBeGreaterThan(generation);
    expect(getAccessToken()).toBe(token);
    expect(expired).not.toHaveBeenCalled();
    if (name === "logout") {
      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/auth\/logout$/);
      expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "POST", credentials: "include" });
      expect(requestHeaders(0).get("Authorization")).toBeNull();
      expect(fetchMock.mock.calls[0][1]?.body).toBeUndefined();
    } else {
      // In particular, the old POST body must never be sent with a new user's bearer.
      expect(fetchMock).not.toHaveBeenCalled();
    }
  });
});
