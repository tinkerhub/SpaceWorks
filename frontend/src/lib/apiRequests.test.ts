import { accessToken } from "../test/accessTokens";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { tenantPublicRequest } from "./apiRequests";
import {
  cacheTenantPublishableKey, clearAccessToken, getAccessToken, setAccessToken,
  setRuntimePublishableKey, tenantPublishableKeys,
} from "./apiSession";

const fetchMock = vi.fn<typeof fetch>();

function respond(status: number, body: unknown = {}) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
}

function authorizationOf(call: number) {
  const headers = fetchMock.mock.calls[call][1]?.headers as Record<string, string>;
  return headers.Authorization;
}

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  setAccessToken(accessToken("previous-session")); // Seed the tab's intended identity before clearing its bearer.
  clearAccessToken();
  setRuntimePublishableKey("");
  tenantPublishableKeys.clear();
  cacheTenantPublishableKey("forge", "pk_forge");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("tenantPublicRequest session restore", () => {
  it("exchanges the refresh cookie once on 401 and retries with the new token", async () => {
    fetchMock
      .mockImplementationOnce(() => respond(401, { detail: "Authentication credentials were not provided." }))
      .mockImplementationOnce(() => respond(200, { access: accessToken("fresh-access") }))
      .mockImplementationOnce(() => respond(201, { status: "registered" }));

    await expect(tenantPublicRequest("forge", "/public/forge/events/x/register/", { method: "POST", body: "{}" }))
      .resolves.toEqual({ status: "registered" });
    expect(String(fetchMock.mock.calls[1][0])).toMatch(/\/auth\/refresh$/);
    expect(authorizationOf(0)).toBeUndefined();
    expect(authorizationOf(2)).toBe(`Bearer ${accessToken("fresh-access")}`);
    expect(getAccessToken()).toBe(accessToken("fresh-access"));
  });

  it("surfaces the original 401 when there is no session to restore", async () => {
    fetchMock
      .mockImplementationOnce(() => respond(401, { detail: "Authentication credentials were not provided." }))
      .mockImplementationOnce(() => respond(401));

    await expect(tenantPublicRequest("forge", "/public/forge/spaces/x/book/", { method: "POST", body: "{}" }))
      .rejects.toMatchObject({ status: 401 });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("drops a dead token that cannot be renewed and retries once anonymously", async () => {
    setAccessToken(accessToken("expired-access"));
    fetchMock
      .mockImplementationOnce(() => respond(401, { detail: "Token is invalid or expired" }))
      .mockImplementationOnce(() => respond(401))
      .mockImplementationOnce(() => respond(200, { results: [] }));

    await expect(tenantPublicRequest("forge", "/public/forge/machines")).resolves.toEqual({ results: [] });
    expect(authorizationOf(0)).toBe(`Bearer ${accessToken("expired-access")}`);
    expect(authorizationOf(2)).toBeUndefined();
    expect(getAccessToken()).toBe("");
  });

  it("does not refresh on other errors", async () => {
    fetchMock.mockImplementationOnce(() => respond(403, { code: "membership_required" }));

    await expect(tenantPublicRequest("forge", "/public/forge/tools/checkout", { method: "POST", body: "{}" }))
      .rejects.toMatchObject({ status: 403 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
