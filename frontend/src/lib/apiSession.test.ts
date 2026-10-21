import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getAccessToken, logout, LogoutIncompleteError, refreshAccessToken, setAccessToken } from "./apiSession";

const fetchMock = vi.fn<typeof fetch>();

function respond(status: number, body: unknown = {}) {
  // A 204 may not carry a body.
  return Promise.resolve(new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
}

beforeEach(() => {
  window.localStorage.clear();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  setAccessToken("live-access");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("logout", () => {
  it("clears the token and leaves refresh working after a confirmed logout", async () => {
    fetchMock.mockImplementationOnce(() => respond(204));
    await expect(logout()).resolves.toBeUndefined();
    expect(getAccessToken()).toBe("");

    fetchMock.mockImplementationOnce(() => respond(401));
    await expect(refreshAccessToken()).resolves.toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it.each([
    ["a server error", () => respond(500)],
    ["a network failure", () => Promise.reject(new TypeError("Failed to fetch"))],
  ])("throws on %s and never refreshes the surviving cookie back in", async (_label, failure) => {
    fetchMock.mockImplementationOnce(failure);
    await expect(logout()).rejects.toBeInstanceOf(LogoutIncompleteError);
    expect(getAccessToken()).toBe("");

    // A later refetch hits 401 and tries to refresh: the cookie may still be valid
    // server-side, so no request may go out and the session stays signed out.
    fetchMock.mockImplementation(() => respond(200, { access: "resurrected" }));
    await expect(refreshAccessToken()).resolves.toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(getAccessToken()).toBe("");
  });

  it("lets a fresh sign-in lift the latch", async () => {
    fetchMock.mockImplementationOnce(() => respond(503));
    await expect(logout()).rejects.toBeInstanceOf(LogoutIncompleteError);

    setAccessToken("signed-in-again");
    fetchMock.mockImplementationOnce(() => respond(200, { access: "rotated" }));
    await expect(refreshAccessToken()).resolves.toBe(true);
    expect(getAccessToken()).toBe("rotated");
  });
});
