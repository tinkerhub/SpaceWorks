import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { accessToken } from "../test/accessTokens";
import { held, LATCH_KEY, PIN_KEY, reloadSession, response, tabStorage } from "./refreshPinTestHelpers";

let storage: ReturnType<typeof tabStorage>;
let session: Awaited<ReturnType<typeof reloadSession>>;
const fetchMock = vi.fn<typeof fetch>();
const tokenA = accessToken("A");
const tokenB = accessToken("B", { user_id: 2 });
beforeEach(async () => {
  localStorage.clear();
  storage = tabStorage();
  vi.spyOn(window, "sessionStorage", "get").mockReturnValue(storage);
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  session = await reloadSession();
  session.setAccessToken(tokenA);
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("atomic explicit session installation", () => {
  it.each(["throwing write", "no-op write", "throwing read-back"])(
    "allows memory B only after confirmed old-pin removal with %s", async (failure) => {
      const epoch = session.getSessionGeneration();
      if (failure === "throwing write") storage.setItem.mockImplementation(() => { throw new Error("quota"); });
      if (failure === "no-op write") storage.setItem.mockImplementation(() => {});
      if (failure === "throwing read-back") storage.getItem.mockImplementationOnce(() => { throw new Error("read denied"); });
      session.setAccessToken(tokenB);
      expect(storage.removeItem).toHaveBeenCalledExactlyOnceWith(PIN_KEY);
      expect(storage.getItem(PIN_KEY)).toBeNull();
      expect(session.getAccessToken()).toBe(tokenB);
      expect(session.getSessionGeneration()).toBe(epoch + 1);
      fetchMock.mockResolvedValueOnce(response(accessToken("B-rotation", { user_id: 2 })));
      await expect(session.refreshAccessToken()).resolves.toBe(true);
      expect(session.getAccessToken()).toBe(accessToken("B-rotation", { user_id: 2 }));
      const reloaded = await reloadSession();
      await expect(reloaded.refreshAccessToken()).resolves.toBe(false);
      expect(reloaded.getAccessToken()).toBe("");
      expect(fetchMock).toHaveBeenCalledTimes(1);
    },
  );

  it.each(["throw", "no-op"])("uses a verified invalid marker when removal is a %s", async (mode) => {
    const write = storage.setItem.getMockImplementation()!;
    storage.setItem.mockImplementation((key, value) => {
      if (JSON.parse(value).user_id === "2") throw new Error("B write failed");
      write(key, value);
    });
    storage.removeItem.mockImplementation(() => { if (mode === "throw") throw new Error("removal denied"); });
    session.setAccessToken(tokenB);
    expect(session.getAccessToken()).toBe(tokenB);
    expect(storage.getItem(PIN_KEY)).toBe('{"version":1,"invalidated":true}');
    const reloaded = await reloadSession();
    await expect(reloaded.refreshAccessToken()).resolves.toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each(["throw", "no-op"])("rejects replacement atomically when all persistence and invalidation operations %s", async (mode) => {
    const { SessionInstallError } = await import("./sessionIntent");
    const epoch = session.getSessionGeneration();
    const pinA = storage.getItem(PIN_KEY);
    localStorage.setItem("makerspace.access", "untouched-legacy");
    localStorage.setItem(LATCH_KEY, "1");
    const fail = () => { if (mode === "throw") throw new Error("storage blocked"); };
    storage.setItem.mockImplementation(fail);
    storage.removeItem.mockImplementation(fail);
    expect(() => session.setAccessToken(tokenB)).toThrow(SessionInstallError);
    expect(() => session.setAccessToken(tokenB)).toThrow(expect.objectContaining({
      code: "session_install_failed", reason: "storage_unavailable",
    }));
    expect(session.getAccessToken()).toBe(tokenA);
    expect(session.getSessionGeneration()).toBe(epoch);
    expect(storage.getItem(PIN_KEY)).toBe(pinA);
    expect(localStorage.getItem(LATCH_KEY)).toBe("1");
    expect(localStorage.getItem("makerspace.access")).toBe("untouched-legacy");
  });

  it("does not treat unreadable storage as proof of persistence or invalidation", async () => {
    const epoch = session.getSessionGeneration();
    storage.getItem.mockImplementation(() => { throw new Error("read blocked"); });
    expect(() => session.setAccessToken(tokenB)).toThrow(expect.objectContaining({
      code: "session_install_failed", reason: "storage_unavailable",
    }));
    expect(storage.removeItem).toHaveBeenCalledWith(PIN_KEY);
    expect(session.getAccessToken()).toBe(tokenA);
    expect(session.getSessionGeneration()).toBe(epoch);
    // Even though writes/removal ran, the application must not claim they were verified.
    const reloaded = await reloadSession();
    await expect(reloaded.refreshAccessToken()).resolves.toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("accepts a throwing write only if read-back proves the exact new pin was saved", () => {
    const write = storage.setItem.getMockImplementation()!;
    storage.setItem.mockImplementation((key, value) => { write(key, value); throw new Error("post-write failure"); });
    const epoch = session.getSessionGeneration();
    session.setAccessToken(tokenB);
    expect(JSON.parse(storage.getItem(PIN_KEY)!).user_id).toBe("2");
    expect(storage.removeItem).not.toHaveBeenCalled();
    expect(session.getAccessToken()).toBe(tokenB);
    expect(session.getSessionGeneration()).toBe(epoch + 1);
  });

  it("leaves an already pending matching refresh owned by A when B installation fails", async () => {
    const pending = held<Response>();
    fetchMock.mockReturnValueOnce(pending.promise);
    const refreshing = session.refreshAccessToken();
    const epoch = session.getSessionGeneration();
    storage.setItem.mockImplementation(() => {});
    storage.removeItem.mockImplementation(() => {});
    expect(() => session.setAccessToken(tokenB)).toThrow(expect.objectContaining({ reason: "storage_unavailable" }));
    const rotatedA = accessToken("A-rotation");
    pending.resolve(response(rotatedA));
    await expect(refreshing).resolves.toBe(true);
    expect(session.getAccessToken()).toBe(rotatedA);
    expect(session.getSessionGeneration()).toBe(epoch);
  });

  it("rejects an invalid token before storage work and preserves the prior session", async () => {
    const { SessionInstallError } = await import("./sessionIntent");
    const epoch = session.getSessionGeneration();
    const pin = storage.getItem(PIN_KEY);
    storage.setItem.mockClear();
    expect(() => session.setAccessToken("opaque")).toThrow(SessionInstallError);
    expect(() => session.setAccessToken("")).toThrow(expect.objectContaining({ reason: "invalid_token" }));
    expect(storage.setItem).not.toHaveBeenCalled();
    expect(storage.removeItem).not.toHaveBeenCalled();
    expect(storage.getItem(PIN_KEY)).toBe(pin);
    expect(session.getAccessToken()).toBe(tokenA);
    expect(session.getSessionGeneration()).toBe(epoch);
  });
});
