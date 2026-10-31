import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { accessToken } from "../test/accessTokens";
import {
  claimContext, generation, held, nextGeneration, PIN_KEY, reloadSession, response, tabStorage,
} from "./refreshPinTestHelpers";

const fetchMock = vi.fn<typeof fetch>();
beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("per-tab refresh intent", () => {
  it("persists exactly the versioned identity, without the bearer, rotating claims or PII", async () => {
    const session = await reloadSession();
    localStorage.setItem("makerspace.access", "legacy-bearer");
    session.setAccessToken(accessToken("private-label", {
      email: "private@example.test", username: "Private Member", phone: "+15550000000",
    }));
    expect(JSON.parse(sessionStorage.getItem(PIN_KEY)!)).toEqual({
      version: 1, user_id: "1", auth_generation: generation, token_type: "access", surface: "member",
    });
    expect(sessionStorage.length).toBe(1);
    expect(localStorage.getItem(PIN_KEY)).toBeNull();
    expect(localStorage.getItem("makerspace.access")).toBeNull();
  });

  it.each([
    { name: "member", context: {} },
    { name: "platform staff", context: { surface: "staff", staff_scope: "platform" } },
    { name: "tenant staff", context: { surface: "staff", staff_scope: "9" } },
    { name: "staff API", context: { surface: "staff_api" } },
    { name: "verification", context: { surface: "verification_only" } },
    { name: "claim member", context: claimContext },
  ])("restores matching $name rotation after reload without advancing its epoch", async ({ context }) => {
    const initial = await reloadSession();
    initial.setAccessToken(accessToken("login", context));
    const pin = sessionStorage.getItem(PIN_KEY);
    const reloaded = await reloadSession();
    expect(reloaded.getAccessToken()).toBe("");
    const epoch = reloaded.getSessionGeneration();
    const rotated = accessToken("rotation", { ...context, jti: "rotated-jti", iat: 42, exp: 99 });
    fetchMock.mockResolvedValueOnce(response(rotated));
    await expect(reloaded.refreshAccessToken()).resolves.toBe(true);
    expect(reloaded.getAccessToken()).toBe(rotated);
    expect(reloaded.getSessionGeneration()).toBe(epoch);
    expect(sessionStorage.getItem(PIN_KEY)).toBe(pin);
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith(expect.stringMatching(/\/auth\/refresh$/), {
      method: "POST", credentials: "include", headers: { "X-Refresh-CSRF": "1" },
    });
  });

  it("rejects cookie A delivered after explicit B, including on a fresh module reload", async () => {
    const session = await reloadSession();
    session.setAccessToken(accessToken("login-A"));
    const late = held<Response>();
    fetchMock.mockReturnValueOnce(late.promise);
    const oldRefresh = session.refreshAccessToken();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const tokenB = accessToken("login-B", { user_id: 2 });
    session.setAccessToken(tokenB);
    const epochB = session.getSessionGeneration();
    const pinB = sessionStorage.getItem(PIN_KEY);
    // Model ordered HTTP Set-Cookie delivery: B's login completes first, then A's
    // older response replaces the browser cookie. Backend ordering is tested separately.
    let browserCookieAccess = tokenB;
    expect(browserCookieAccess).toBe(session.getAccessToken());
    browserCookieAccess = accessToken("late-cookie-A");
    late.resolve(response(browserCookieAccess));
    await expect(oldRefresh).resolves.toBe(false);
    expect(session.getAccessToken()).toBe(tokenB);
    expect(session.getSessionGeneration()).toBe(epochB);
    expect(sessionStorage.getItem(PIN_KEY)).toBe(pinB);

    const reloaded = await reloadSession();
    fetchMock.mockResolvedValueOnce(response(browserCookieAccess));
    const reloadEpoch = reloaded.getSessionGeneration();
    await expect(reloaded.refreshAccessToken()).resolves.toBe(false);
    expect(reloaded.getAccessToken()).toBe("");
    expect(reloaded.getSessionGeneration()).toBe(reloadEpoch);
    expect(sessionStorage.getItem(PIN_KEY)).toBe(pinB);
    browserCookieAccess = accessToken("matching-cookie-B", { user_id: 2 });
    fetchMock.mockResolvedValueOnce(response(browserCookieAccess));
    await expect(reloaded.refreshAccessToken()).resolves.toBe(true);
    expect(reloaded.getAccessToken()).toBe(browserCookieAccess);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it.each([
    { name: "deployment generation", initial: {}, changed: { auth_generation: nextGeneration } },
    { name: "surface", initial: {}, changed: { surface: "verification_only" } },
    { name: "staff scope", initial: { surface: "staff", staff_scope: "9" },
      changed: { surface: "staff", staff_scope: "platform" } },
    { name: "claim session", initial: claimContext,
      changed: { ...claimContext, claim_session_id: nextGeneration } },
    { name: "claim membership", initial: claimContext,
      changed: { ...claimContext, claim_membership_id: 8 } },
    { name: "claim makerspace", initial: claimContext,
      changed: { ...claimContext, claim_makerspace_id: 10 } },
  ])("rejects a valid refresh with a changed $name without clearing the current session", async ({ initial, changed }) => {
    const session = await reloadSession();
    const token = accessToken("current", initial);
    session.setAccessToken(token);
    const epoch = session.getSessionGeneration();
    const pin = sessionStorage.getItem(PIN_KEY);
    fetchMock.mockResolvedValueOnce(response(accessToken("wrong-context", changed)));
    await expect(session.refreshAccessToken()).resolves.toBe(false);
    expect(session.getAccessToken()).toBe(token);
    expect(session.getSessionGeneration()).toBe(epoch);
    expect(sessionStorage.getItem(PIN_KEY)).toBe(pin);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each([null, "{", '{"version":1,"invalidated":true}', '{"version":1,"user_id":"1"}'])(
    "never fetches with a missing or invalid reload pin %#", async (pin) => {
      if (pin !== null) sessionStorage.setItem(PIN_KEY, pin);
      // A valid cookie alone cannot select an identity, even with a legacy bearer on disk.
      localStorage.setItem("makerspace.access", accessToken("legacy"));
      fetchMock.mockResolvedValue(response(accessToken("cookie-only")));
      const reloaded = await reloadSession();
      await expect(reloaded.refreshAccessToken()).resolves.toBe(false);
      expect(reloaded.getAccessToken()).toBe("");
      expect(fetchMock).not.toHaveBeenCalled();
    },
  );

  it("preserves the pin across a local bearer clear for later matching anonymous recovery", async () => {
    const session = await reloadSession();
    session.setAccessToken(accessToken("login"));
    const pin = sessionStorage.getItem(PIN_KEY);
    const epoch = session.getSessionGeneration();
    session.clearAccessToken();
    expect(session.getSessionGeneration()).toBe(epoch + 1);
    expect(sessionStorage.getItem(PIN_KEY)).toBe(pin);
    const reloaded = await reloadSession();
    fetchMock.mockResolvedValueOnce(response(accessToken("recovery")));
    await expect(reloaded.refreshAccessToken()).resolves.toBe(true);
    expect(reloaded.getAccessToken()).toBe(accessToken("recovery"));
  });

  it("an opener-cloned pin accepts only its original context after the parent changes account", async () => {
    const parentStore = tabStorage();
    let active: Storage = parentStore;
    vi.spyOn(window, "sessionStorage", "get").mockImplementation(() => active);
    const parent = await reloadSession();
    parent.setAccessToken(accessToken("parent-A"));
    const childStore = tabStorage(parentStore);
    const originalPin = childStore.getItem(PIN_KEY);
    active = childStore;
    const child = await reloadSession();
    active = parentStore;
    parent.setAccessToken(accessToken("parent-B", { user_id: 2 }));
    expect(childStore.getItem(PIN_KEY)).toBe(originalPin);
    active = childStore;
    fetchMock.mockResolvedValueOnce(response(accessToken("shared-cookie-B", { user_id: 2 })));
    await expect(child.refreshAccessToken()).resolves.toBe(false);
    expect(child.getAccessToken()).toBe("");
    fetchMock.mockResolvedValueOnce(response(accessToken("child-A-rotation")));
    await expect(child.refreshAccessToken()).resolves.toBe(true);
    expect(child.getAccessToken()).toBe(accessToken("child-A-rotation"));
    expect(parent.getAccessToken()).toBe(accessToken("parent-B", { user_id: 2 }));
  });

  it("independent tabs retain different pins and reject the other tab's cookie identity", async () => {
    const storeA = tabStorage();
    const storeB = tabStorage();
    let active: Storage = storeA;
    vi.spyOn(window, "sessionStorage", "get").mockImplementation(() => active);
    const tabA = await reloadSession();
    tabA.setAccessToken(accessToken("A"));
    active = storeB;
    const tabB = await reloadSession();
    tabB.setAccessToken(accessToken("B", { user_id: 2 }));
    const pinB = storeB.getItem(PIN_KEY);
    active = storeA;
    const reloadA = await reloadSession();
    fetchMock.mockResolvedValueOnce(response(accessToken("B-cookie", { user_id: 2 })));
    await expect(reloadA.refreshAccessToken()).resolves.toBe(false);
    fetchMock.mockResolvedValueOnce(response(accessToken("A-rotation")));
    await expect(reloadA.refreshAccessToken()).resolves.toBe(true);
    active = storeB;
    const reloadB = await reloadSession();
    fetchMock.mockResolvedValueOnce(response(accessToken("B-rotation", { user_id: 2 })));
    await expect(reloadB.refreshAccessToken()).resolves.toBe(true);
    expect(storeB.getItem(PIN_KEY)).toBe(pinB);
    expect(JSON.parse(storeA.getItem(PIN_KEY)!).user_id).toBe("1");
    expect(JSON.parse(pinB!).user_id).toBe("2");
    expect(reloadA.getAccessToken()).toBe(accessToken("A-rotation"));
    expect(reloadB.getAccessToken()).toBe(accessToken("B-rotation", { user_id: 2 }));
  });
});
