import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { forgetRequestCapabilities, revealRequestCapabilities, saveRequestCapability } from "./requestCapabilities";

const key = "spaceworks.requests.a";
beforeEach(() => localStorage.clear());
afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });

describe("truthful local storage outcomes", () => {
  it.each(["{broken", "x".repeat(64_001), JSON.stringify(Array(51).fill({ kind: "hardware", token: "x", saved_at: 1 })),
    JSON.stringify([{ kind: "unknown", token: "x", saved_at: 1 }]),
    JSON.stringify([{ kind: "hardware", token: "x", saved_at: -1 }])])(
    "does not overwrite unreadable data; Forget all clears exact tenant keys without parsing", (raw) => {
      localStorage.setItem(key, raw);
      localStorage.setItem("tinkerspace.serviceStatus.a", "reachable-legacy");
      localStorage.setItem("tinkerspace.printStatus.a", "printer");
      const others = ["spaceworks.requests.ab", "spaceworks.requests.b", "tinkerspace.printStatus.b", "unrelated"];
      others.forEach((name) => localStorage.setItem(name, "leave-me"));
      expect(saveRequestCapability("a", "hardware", "new")).toMatchObject({ saved: false, warning: expect.any(String) });
      const reveal = revealRequestCapabilities("a");
      expect(reveal).toMatchObject({ saved: false, warning: expect.any(String) });
      expect(reveal.records.map((row) => row.token)).toContain("reachable-legacy");
      expect(localStorage.getItem(key)).toBe(raw);
      expect(localStorage.getItem("tinkerspace.serviceStatus.a")).toBe("reachable-legacy");
      expect(forgetRequestCapabilities("a")).toEqual({ saved: true, records: [] });
      for (const name of [key, "tinkerspace.serviceStatus.a", "tinkerspace.printStatus.a"]) expect(localStorage.getItem(name)).toBeNull();
      others.forEach((name) => expect(localStorage.getItem(name)).toBe("leave-me"));
      expect(revealRequestCapabilities("a").records).toEqual([]);
    });

  it.each(["set throws", "set discarded", "readback differs"])("keeps legacy reachable when registry verification fails: %s", (failure) => {
    localStorage.setItem("tinkerspace.serviceStatus.a", "old service");
    const set = Storage.prototype.setItem, get = Storage.prototype.getItem;
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (this: Storage, name, value) {
      if (name === key) {
        if (failure === "set throws") throw new Error("Quota");
        if (failure === "set discarded") return;
      }
      set.call(this, name, value);
    });
    if (failure === "readback differs") vi.spyOn(Storage.prototype, "getItem").mockImplementation(function (this: Storage, name) {
      const value = get.call(this, name);
      return name === key && value ? "[]" : value;
    });
    const result = revealRequestCapabilities("a");
    expect(result).toMatchObject({ saved: false, warning: expect.any(String) });
    expect(result.records).toEqual([{ kind: "machine", token: "old service", saved_at: expect.any(Number) }]);
    expect(localStorage.getItem("tinkerspace.serviceStatus.a")).toBe("old service");
    expect(saveRequestCapability("a", "hardware", "fresh")).toMatchObject({ saved: false, warning: expect.any(String) });
  });

  it("reports unavailable reads without erasing the registry", () => {
    saveRequestCapability("a", "hardware", "kept");
    const raw = localStorage.getItem(key);
    const read = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("Denied"); });
    const write = vi.spyOn(Storage.prototype, "setItem");
    expect(revealRequestCapabilities("a")).toMatchObject({ saved: false, warning: expect.any(String) });
    expect(saveRequestCapability("a", "hardware", "new").saved).toBe(false);
    expect(write).not.toHaveBeenCalled();
    read.mockRestore();
    expect(localStorage.getItem(key)).toBe(raw);
  });

  it.each(["throws", "silently retained"])("does not claim forgetting when legacy removal %s", (failure) => {
    saveRequestCapability("a", "machine", "kept");
    const remove = Storage.prototype.removeItem;
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(function (this: Storage, name) {
      if (name === "tinkerspace.serviceStatus.a") {
        if (failure === "throws") throw new Error("Denied");
        return;
      }
      remove.call(this, name);
    });
    const result = forgetRequestCapabilities("a", { kind: "machine", token: "kept", saved_at: 0 });
    expect(result).toMatchObject({ saved: false, warning: expect.stringContaining("may appear again") });
    expect(localStorage.getItem("tinkerspace.serviceStatus.a")).toBe("kept");
    expect(forgetRequestCapabilities("a").saved).toBe(false);
    expect(revealRequestCapabilities("a").records.map((row) => row.token)).toContain("kept");
  });
});
