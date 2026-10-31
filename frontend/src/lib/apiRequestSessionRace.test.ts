import { accessToken } from "../test/accessTokens";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StructuredApiError } from "./apiErrors";
import {
  memberRequest, memberRequestBlob, staffRequest, staffRequestBlob,
  tenantPublicRequest, tenantPublicRequestBlob,
} from "./apiRequests";
import {
  addAuthExpiredListener, clearAccessToken, getAccessToken, logout, setAccessToken,
} from "./apiSession";
import { fetchMock, heldResponse, jsonResponse, requestHeaders, resetSessionTransport } from "./apiSessionTestHelpers";

const cases = [
  { name: "staff JSON", request: () => staffRequest("/admin/tools"), public: false },
  { name: "staff blob", request: () => staffRequestBlob("/admin/export"), public: false },
  { name: "member JSON", request: () => memberRequest("/member/profile"), public: false },
  { name: "member blob", request: () => memberRequestBlob("/member/calendar"), public: false },
  { name: "tenant public JSON", request: () => tenantPublicRequest("forge", "/public/forge/tools"), public: true },
  { name: "tenant public blob", request: () => tenantPublicRequestBlob("forge", "/public/forge/calendar"), public: true },
];
const expired = vi.fn();
let unsubscribe: () => void;
beforeEach(() => {
  resetSessionTransport();
  expired.mockReset();
  unsubscribe = addAuthExpiredListener(expired);
});
afterEach(() => { unsubscribe(); vi.unstubAllGlobals(); });

async function expectUnauthorized(request: Promise<unknown>) {
  await expect(request).rejects.toBeInstanceOf(StructuredApiError);
  await expect(request).rejects.toMatchObject({ status: 401 });
}

describe.each(cases)("$name session races", ({ request }) => {
  describe.each(["initial 401", "refresh response", "retried 401"] as const)("held %s", (boundary) => {
    it.each([
      { name: "new account", login: accessToken("new-account", { user_id: 2 }) },
      { name: "same token", login: accessToken("old-access") },
    ])("does not replay or expire a newer login ($name)", async ({ login }) => {
      const held = heldResponse();
      if (boundary !== "initial 401") fetchMock.mockResolvedValueOnce(jsonResponse(401));
      if (boundary === "retried 401") fetchMock.mockResolvedValueOnce(jsonResponse(200, { access: accessToken("rotated-old") }));
      fetchMock.mockImplementationOnce(held.send);
      const pending = expectUnauthorized(request());
      await held.entered;
      setAccessToken(login);
      held.resolve(jsonResponse(boundary === "refresh response" ? 200 : 401, { access: accessToken("obsolete") }));
      await pending;

      expect(getAccessToken()).toBe(login);
      expect(expired).not.toHaveBeenCalled();
      const expectedCalls = boundary === "initial 401" ? 1 : boundary === "refresh response" ? 2 : 3;
      expect(fetchMock).toHaveBeenCalledTimes(expectedCalls);
      expect(requestHeaders(0).get("Authorization")).toBe(`Bearer ${accessToken("old-access")}`);
      if (boundary === "retried 401") {
        expect(requestHeaders(2).get("Authorization")).toBe(`Bearer ${accessToken("rotated-old")}`);
      }
    });
  });

  it.each(["clear", "logout"])("does not resurrect or retry after %s during refresh", async (action) => {
    const held = heldResponse();
    fetchMock.mockResolvedValueOnce(jsonResponse(401)).mockImplementationOnce(held.send);
    const pending = expectUnauthorized(request());
    await held.entered;
    if (action === "logout") {
      fetchMock.mockResolvedValueOnce(jsonResponse(204));
      await logout();
    } else clearAccessToken();
    held.resolve(jsonResponse(200, { access: accessToken("obsolete") }));
    await pending;
    expect(getAccessToken()).toBe("");
    expect(expired).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(action === "logout" ? 3 : 2);
  });

  it("recovers an unchanged session with exactly one authenticated retry", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(401))
      .mockResolvedValueOnce(jsonResponse(200, { access: accessToken("fresh") }))
      .mockResolvedValueOnce(jsonResponse(200, { result: "ok" }));
    await expect(request()).resolves.toBeDefined();
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(String(fetchMock.mock.calls[1][0])).toMatch(/\/auth\/refresh$/);
    expect(requestHeaders(0).get("Authorization")).toBe(`Bearer ${accessToken("old-access")}`);
    expect(requestHeaders(2).get("Authorization")).toBe(`Bearer ${accessToken("fresh")}`);
    expect(getAccessToken()).toBe(accessToken("fresh"));
    expect(expired).not.toHaveBeenCalled();
  });
});

describe.each(cases.filter((entry) => !entry.public))("$name expiry", ({ request }) => {
  it.each(["failed refresh", "retried 401"])("clears and notifies exactly once for %s", async (failure) => {
    fetchMock.mockResolvedValueOnce(jsonResponse(401))
      .mockResolvedValueOnce(jsonResponse(failure === "failed refresh" ? 401 : 200, { access: accessToken("fresh") }));
    if (failure === "retried 401") fetchMock.mockResolvedValueOnce(jsonResponse(401));
    await expectUnauthorized(request());
    expect(getAccessToken()).toBe("");
    expect(expired).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(failure === "failed refresh" ? 2 : 3);
  });
});

describe.each(cases.filter((entry) => entry.public))("$name bounded recovery", ({ request }) => {
  it("clears a dead bearer and falls back anonymously once without a refresh loop", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(401))
      .mockResolvedValueOnce(jsonResponse(401))
      .mockResolvedValueOnce(jsonResponse(401));
    await expectUnauthorized(request());
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(requestHeaders(2).get("Authorization")).toBeNull();
    expect(requestHeaders(2).get("X-Publishable-Key")).toBe("pk_forge");
    expect(getAccessToken()).toBe("");
    expect(expired).not.toHaveBeenCalled();
  });

  it("rejects without anonymous replay when neither bearer nor refresh session exists", async () => {
    clearAccessToken();
    fetchMock.mockResolvedValueOnce(jsonResponse(401)).mockResolvedValueOnce(jsonResponse(401));
    await expectUnauthorized(request());
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(requestHeaders(0).get("Authorization")).toBeNull();
    expect(expired).not.toHaveBeenCalled();
  });

  it("does not loop when the refreshed bearer is also rejected", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(401))
      .mockResolvedValueOnce(jsonResponse(200, { access: accessToken("fresh") }))
      .mockResolvedValueOnce(jsonResponse(401));
    await expectUnauthorized(request());
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(expired).not.toHaveBeenCalled();
  });
});
