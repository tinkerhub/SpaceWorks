import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { accessToken } from "../test/accessTokens";
import { held, LATCH_KEY, PIN_KEY, reloadSession, response, tabStorage } from "./refreshPinTestHelpers";

const fetchMock = vi.fn<typeof fetch>();
beforeEach(() => { localStorage.clear(); fetchMock.mockReset(); vi.stubGlobal("fetch", fetchMock); });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("logout durability and truthful failures", () => {
  it.each([
    { name: "server only", status: 503, storage: "working", reason: "server_unconfirmed" },
    { name: "storage only", status: 204, storage: "stale", reason: "storage_unavailable" },
    { name: "server and storage", status: 503, storage: "stale", reason: "server_and_storage_unconfirmed" },
    { name: "unreadable storage", status: 204, storage: "unreadable", reason: "storage_unavailable" },
    { name: "network and storage", status: null, storage: "stale", reason: "server_and_storage_unconfirmed" },
  ])("always attempts server logout and reports $name accurately", async ({ status, storage: failure, reason }) => {
    const storage = tabStorage();
    vi.spyOn(window, "sessionStorage", "get").mockReturnValue(storage);
    const session = await reloadSession();
    session.setAccessToken(accessToken("A"));
    if (failure === "stale") {
      storage.removeItem.mockImplementation(() => {});
      storage.setItem.mockImplementation(() => {});
    } else if (failure === "unreadable") {
      storage.getItem.mockImplementation(() => { throw new Error("read denied"); });
    }
    if (status === null) fetchMock.mockRejectedValueOnce(new TypeError("offline"));
    else fetchMock.mockResolvedValueOnce(response(undefined, status));
    const loggingOut = session.logout();
    expect(session.getAccessToken()).toBe("");
    expect(localStorage.getItem(LATCH_KEY)).toBe("1");
    await expect(loggingOut).rejects.toBeInstanceOf(session.LogoutIncompleteError);
    await expect(loggingOut).rejects.toMatchObject({ reason });
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith(expect.stringMatching(/\/auth\/logout$/), {
      method: "POST", credentials: "include", headers: { "X-Refresh-CSRF": "1" },
    });
    await expect(session.refreshAccessToken()).resolves.toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each(["removed pin", "invalid marker"])(
    "proves per-tab logout with %s even after a new tab's login clears the shared latch", async (proof) => {
      const storeA = tabStorage();
      let active: Storage = storeA;
      vi.spyOn(window, "sessionStorage", "get").mockImplementation(() => active);
      const tabA = await reloadSession();
      tabA.setAccessToken(accessToken("A"));
      if (proof === "invalid marker") storeA.removeItem.mockImplementation(() => { throw new Error("remove denied"); });
      // Keep the server cookie alive; reload safety must come from A's own pin.
      fetchMock.mockResolvedValueOnce(response(undefined, 503));
      await expect(tabA.logout()).rejects.toMatchObject({ reason: "server_unconfirmed" });
      expect(storeA.getItem(PIN_KEY)).toBe(proof === "removed pin" ? null : '{"version":1,"invalidated":true}');
      active = tabStorage();
      const tabB = await reloadSession();
      tabB.setAccessToken(accessToken("B", { user_id: 2 }));
      expect(localStorage.getItem(LATCH_KEY)).toBeNull();
      active = storeA;
      const reloadA = await reloadSession();
      fetchMock.mockResolvedValue(response(accessToken("surviving-A-cookie")));
      await expect(reloadA.refreshAccessToken()).resolves.toBe(false);
      expect(reloadA.getAccessToken()).toBe("");
      expect(tabB.getAccessToken()).toBe(accessToken("B", { user_id: 2 }));
      expect(fetchMock).toHaveBeenCalledTimes(1);
    },
  );

  it("cannot call a shared latch durable when an old pin survives and another tab can clear the latch", async () => {
    const storeA = tabStorage();
    let active: Storage = storeA;
    vi.spyOn(window, "sessionStorage", "get").mockImplementation(() => active);
    const tabA = await reloadSession();
    tabA.setAccessToken(accessToken("A"));
    storeA.removeItem.mockImplementation(() => {});
    storeA.setItem.mockImplementation(() => {});
    fetchMock.mockResolvedValueOnce(response(undefined, 204));
    await expect(tabA.logout()).rejects.toMatchObject({ reason: "storage_unavailable" });
    expect(JSON.parse(storeA.getItem(PIN_KEY)!).user_id).toBe("1");
    await expect(tabA.refreshAccessToken()).resolves.toBe(false);
    active = tabStorage();
    const tabB = await reloadSession();
    tabB.setAccessToken(accessToken("B", { user_id: 2 }));
    expect(localStorage.getItem(LATCH_KEY)).toBeNull();
    active = storeA;
    const reloadA = await reloadSession();
    // An old/in-flight cookie may survive HTTP logout. This is exactly why the
    // earlier result must warn about reload, even when the logout endpoint said 204.
    fetchMock.mockResolvedValueOnce(response(accessToken("surviving-cookie-A")));
    await expect(reloadA.refreshAccessToken()).resolves.toBe(true);
    expect(reloadA.getAccessToken()).toBe(accessToken("surviving-cookie-A"));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("an incomplete old logout cannot alter a newer login's token, pin, latch or epoch", async () => {
    const storage = tabStorage();
    vi.spyOn(window, "sessionStorage", "get").mockReturnValue(storage);
    const session = await reloadSession();
    session.setAccessToken(accessToken("A"));
    const write = storage.setItem.getMockImplementation()!;
    const remove = storage.removeItem.getMockImplementation()!;
    storage.setItem.mockImplementation(() => {});
    storage.removeItem.mockImplementation(() => {});
    const server = held<Response>();
    fetchMock.mockReturnValueOnce(server.promise);
    const loggingOut = session.logout();
    const failure = expect(loggingOut).rejects.toMatchObject({ reason: "storage_unavailable" });
    expect(session.getAccessToken()).toBe("");
    storage.setItem.mockImplementation(write);
    storage.removeItem.mockImplementation(remove);
    const tokenB = accessToken("B", { user_id: 2 });
    session.setAccessToken(tokenB);
    const epoch = session.getSessionGeneration();
    const pinB = storage.getItem(PIN_KEY);
    server.resolve(response(undefined, 204));
    await failure;
    expect(session.getAccessToken()).toBe(tokenB);
    expect(session.getSessionGeneration()).toBe(epoch);
    expect(storage.getItem(PIN_KEY)).toBe(pinB);
    expect(localStorage.getItem(LATCH_KEY)).toBeNull();
    const reloaded = await reloadSession();
    fetchMock.mockResolvedValueOnce(response(accessToken("B-rotation", { user_id: 2 })));
    await expect(reloaded.refreshAccessToken()).resolves.toBe(true);
    expect(reloaded.getAccessToken()).toBe(accessToken("B-rotation", { user_id: 2 }));
  });
});
