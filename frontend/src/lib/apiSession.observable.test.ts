import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { accessToken } from "../test/accessTokens";
import { deferred, jsonResponse, resetSessionTransport } from "./apiSessionTestHelpers";
import { clearAccessToken, getAccessToken, getSessionGeneration, getSessionRevision, logout,
  refreshAccessToken, setAccessToken, subscribeSession } from "./apiSession";
import { SESSION_INTENT_KEY } from "./sessionIntentStorage";

beforeEach(() => resetSessionTransport(accessToken("original")));
afterEach(() => { clearAccessToken(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("non-secret observable session revision", () => {
  it("exposes a stable integer snapshot and notifies once after a coherent install or clear; unsubscribe stops delivery", () => {
    const before = getSessionRevision(), generation = getSessionGeneration();
    expect(Number.isSafeInteger(before)).toBe(true);
    expect(getSessionRevision()).toBe(before);
    const seen: { revision: number; generation: number; token: string; pin: string | null }[] = [];
    const unsubscribe = subscribeSession(() => seen.push({ revision: getSessionRevision(),
      generation: getSessionGeneration(), token: getAccessToken(), pin: sessionStorage.getItem(SESSION_INTENT_KEY) }));
    const token = accessToken("new", { user_id: 2 });
    setAccessToken(token);
    expect(seen).toEqual([{ revision: before + 1, generation: generation + 1, token,
      pin: sessionStorage.getItem(SESSION_INTENT_KEY) }]);
    expect(JSON.parse(seen[0].pin!).user_id).toBeDefined();
    clearAccessToken();
    expect(seen).toHaveLength(2);
    expect(seen[1]).toMatchObject({ revision: before + 2, generation: generation + 2, token: "" });
    unsubscribe(); setAccessToken(accessToken("after-unsubscribe"));
    expect(seen).toHaveLength(2);
  });

  it("notifies logout with token and durable pin cleared before held HTTP; late completion publishes nothing", async () => {
    const response = deferred<Response>();
    vi.stubGlobal("fetch", vi.fn(() => response.promise));
    const seen: unknown[] = [];
    const unsubscribe = subscribeSession(() => seen.push({ token: getAccessToken(),
      latch: localStorage.getItem("makerspace.signed-out"), pin: sessionStorage.getItem(SESSION_INTENT_KEY) }));
    const pending = logout();
    expect(seen).toEqual([{ token: "", latch: "1", pin: null }]);
    expect(await refreshAccessToken()).toBe(false);
    setAccessToken(accessToken("new-login"));
    const revision = getSessionRevision();
    response.resolve(jsonResponse(200)); await pending;
    expect(getSessionRevision()).toBe(revision);
    expect(getAccessToken()).toBe(accessToken("new-login"));
    expect(seen).toHaveLength(2); unsubscribe();
  });

  it("publishes an accepted refresh with unchanged generation and suppresses a superseded refresh", async () => {
    const revision = getSessionRevision(), generation = getSessionGeneration();
    const listener = vi.fn(); const unsubscribe = subscribeSession(listener);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(jsonResponse(200, { access: accessToken("refreshed") })));
    expect(await refreshAccessToken()).toBe(true);
    expect(listener).toHaveBeenCalledOnce();
    expect(getSessionRevision()).toBe(revision + 1);
    expect(getSessionGeneration()).toBe(generation);
    const response = deferred<Response>(); vi.stubGlobal("fetch", vi.fn(() => response.promise));
    const pending = refreshAccessToken();
    setAccessToken(accessToken("different", { user_id: 2 }));
    listener.mockClear();
    const installed = getSessionRevision();
    response.resolve(jsonResponse(200, { access: accessToken("obsolete") }));
    expect(await pending).toBe(false);
    expect(listener).not.toHaveBeenCalled(); expect(getSessionRevision()).toBe(installed);
    expect(getAccessToken()).toBe(accessToken("different", { user_id: 2 })); unsubscribe();
  });
});
