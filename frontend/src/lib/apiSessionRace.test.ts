import { accessToken } from "../test/accessTokens";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  clearAccessToken, getAccessToken, logout, LogoutIncompleteError,
  refreshAccessToken, setAccessToken,
} from "./apiSession";
import {
  deferred, fetchMock, heldResponse, jsonResponse, resetSessionTransport,
} from "./apiSessionTestHelpers";

beforeEach(() => resetSessionTransport());
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

const invalidations = ["successful logout", "unsuccessful logout", "clear", "new login", "same-token login"] as const;

async function invalidate(kind: typeof invalidations[number]) {
  if (kind === "clear") clearAccessToken();
  else if (kind === "new login") setAccessToken(accessToken("new-access", { user_id: 2 }));
  else if (kind === "same-token login") setAccessToken(accessToken("old-access"));
  else {
    fetchMock.mockResolvedValueOnce(jsonResponse(kind === "successful logout" ? 204 : 503));
    if (kind === "successful logout") await logout();
    else await expect(logout()).rejects.toBeInstanceOf(LogoutIncompleteError);
  }
}

describe.each(["response", "json body"] as const)("refresh held at %s", (boundary) => {
  it.each(invalidations)("cannot overwrite %s", async (kind) => {
    const response = heldResponse();
    const body = deferred<{ access: string }>();
    const readingBody = deferred<void>();
    const success = jsonResponse(200);
    if (boundary === "json body") {
      vi.spyOn(success, "json").mockImplementation(() => {
        readingBody.resolve();
        return body.promise;
      });
      fetchMock.mockResolvedValueOnce(success);
    } else fetchMock.mockImplementationOnce(response.send);
    const refreshing = refreshAccessToken();
    if (boundary === "json body") await readingBody.promise;
    else await response.entered;

    await invalidate(kind);
    const expected = kind === "new login" ? accessToken("new-access", { user_id: 2 }) : kind === "same-token login" ? accessToken("old-access") : "";
    if (boundary === "json body") body.resolve({ access: accessToken("obsolete-refresh") });
    else response.resolve(jsonResponse(200, { access: accessToken("obsolete-refresh") }));
    await expect(refreshing).resolves.toBe(false);
    expect(getAccessToken()).toBe(expected);
    if (kind.includes("logout")) {
      const calls = fetchMock.mock.calls.length;
      await expect(refreshAccessToken()).resolves.toBe(false);
      expect(fetchMock).toHaveBeenCalledTimes(calls);
      expect(localStorage.getItem("makerspace.signed-out")).toBe("1");
    }
  });
});

describe("logout intent and refresh ownership", () => {
  it.each([204, 503])("clears immediately and an old logout %i cannot clear a newer login", async (status) => {
    const held = heldResponse();
    fetchMock.mockImplementationOnce(held.send);
    const loggingOut = logout();
    const completion = status === 204
      ? expect(loggingOut).resolves.toBeUndefined()
      : expect(loggingOut).rejects.toBeInstanceOf(LogoutIncompleteError);
    expect(getAccessToken()).toBe("");
    expect(localStorage.getItem("makerspace.signed-out")).toBe("1");
    await expect(refreshAccessToken()).resolves.toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    setAccessToken(accessToken("new-login", { user_id: 2 }));
    held.resolve(jsonResponse(status));
    await completion;
    expect(getAccessToken()).toBe(accessToken("new-login", { user_id: 2 }));
    expect(localStorage.getItem("makerspace.signed-out")).toBeNull();
  });

  it("keeps successful logout latched after module reload until explicit login", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(204));
    await logout();
    vi.resetModules();
    const reloaded = await import("./apiSession");
    await expect(reloaded.refreshAccessToken()).resolves.toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    reloaded.setAccessToken(accessToken("explicit-login"));
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { access: accessToken("fresh") }));
    await expect(reloaded.refreshAccessToken()).resolves.toBe(true);
    expect(reloaded.getAccessToken()).toBe(accessToken("fresh"));
  });

  it("deduplicates the newer refresh even after the obsolete promise finishes", async () => {
    const old = heldResponse();
    const current = heldResponse();
    fetchMock.mockImplementationOnce(old.send).mockImplementationOnce(current.send);
    const obsolete = refreshAccessToken();
    setAccessToken(accessToken("old-access")); // Same string still establishes a new session.
    const first = refreshAccessToken();
    const second = refreshAccessToken();
    await current.entered;
    expect(fetchMock).toHaveBeenCalledTimes(2);
    old.resolve(jsonResponse(200, { access: accessToken("obsolete") }));
    await expect(obsolete).resolves.toBe(false);
    const third = refreshAccessToken();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    current.resolve(jsonResponse(200, { access: accessToken("current") }));
    await expect(Promise.all([first, second, third])).resolves.toEqual([true, true, true]);
    expect(getAccessToken()).toBe(accessToken("current"));
  });
});
