import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { forgetRequestCapabilities, revealRequestCapabilities, saveRequestCapability, validRequestToken,
  type RequestCapability } from "./requestCapabilities";

const key = "spaceworks.requests.a";
const rows = () => JSON.parse(localStorage.getItem(key)!);
beforeEach(() => { localStorage.clear(); });
afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });

describe("browser capability registry", () => {
  it("retains two hardware and two machine references across readback, dedupes kind+token and isolates tenants", () => {
    for (const kind of ["hardware", "machine"] as const) {
      for (const token of ["one", "two"]) expect(saveRequestCapability("a", kind, token).saved).toBe(true);
    }
    expect(saveRequestCapability("a", "hardware", "one").saved).toBe(true);
    saveRequestCapability("b", "hardware", "only-b");
    const restored = revealRequestCapabilities("a");
    expect(restored.saved).toBe(true);
    expect(restored.records).toHaveLength(4);
    expect(restored.records.map(({ kind, token }) => `${kind}:${token}`).sort()).toEqual([
      "hardware:one", "hardware:two", "machine:one", "machine:two",
    ]);
    for (const record of rows()) expect(Object.keys(record).sort()).toEqual(["kind", "saved_at", "token"]);
    expect(revealRequestCapabilities("b").records).toEqual([
      { kind: "hardware", token: "only-b", saved_at: expect.any(Number) },
    ]);
    expect(localStorage.getItem(key)).not.toMatch(/name|email|title|reason|mid/);
  });

  it("bounds at 50, trims the oldest existing record and refreshes a duplicate instead of adding it", () => {
    localStorage.setItem(key, JSON.stringify(Array.from({ length: 50 }, (_, i) => ({
      kind: "hardware", token: `existing-${i}`, saved_at: i,
    }))));
    saveRequestCapability("a", "hardware", "new");
    expect(rows()).toHaveLength(50);
    expect(rows().some((row: RequestCapability) => row.token === "existing-0")).toBe(false);
    expect(rows().some((row: RequestCapability) => row.token === "existing-49")).toBe(true);
    saveRequestCapability("a", "hardware", "existing-1");
    expect(rows()).toHaveLength(50);
    expect(rows().filter((row: RequestCapability) => row.token === "existing-1")).toHaveLength(1);
  });

  it("keeps a newly successful submission and both imported legacy links reachable against 50 future timestamps", () => {
    const future = Array.from({ length: 50 }, (_, i) => ({ kind: "hardware", token: `future-${i}`, saved_at: 8_000_000_000_000 + i }));
    localStorage.setItem(key, JSON.stringify(future));
    expect(saveRequestCapability("a", "hardware", "just-created").saved).toBe(true);
    expect(rows()).toContainEqual({ kind: "hardware", token: "just-created", saved_at: expect.any(Number) });
    localStorage.setItem("tinkerspace.serviceStatus.a", "old service");
    localStorage.setItem("tinkerspace.printStatus.a", "old-printer");
    const imported = revealRequestCapabilities("a");
    expect(imported.saved).toBe(true);
    expect(imported.records).toHaveLength(50);
    for (const token of ["old service", "old-printer"]) {
      expect(imported.records).toContainEqual({ kind: "machine", token, saved_at: expect.any(Number) });
    }
    expect(localStorage.getItem("tinkerspace.serviceStatus.a")).toBeNull();
    expect(localStorage.getItem("tinkerspace.printStatus.a")).toBeNull();
    expect(revealRequestCapabilities("a").records).toEqual(imported.records);
  });

  it.each(["", " outer", "outer ", "bad\nref", "bad\u007fref", "bad\u0085ref", "\ud800", "x".repeat(513)])(
    "refuses malformed capability %j without altering existing data", (token) => {
      saveRequestCapability("a", "hardware", "kept");
      const before = localStorage.getItem(key);
      expect(validRequestToken(token)).toBe(false);
      expect(saveRequestCapability("a", "hardware", token)).toMatchObject({ saved: false, warning: expect.any(String) });
      expect(localStorage.getItem(key)).toBe(before);
    });

  it("preserves internal spaces, punctuation and a bounded opaque legacy reference", () => {
    for (const token of ["private / & reference", "x".repeat(512)]) {
      expect(validRequestToken(token)).toBe(true);
      expect(saveRequestCapability("a", "hardware", token).saved).toBe(true);
    }
    expect(revealRequestCapabilities("a").records.map((row) => row.token)).toContain("private / & reference");
  });

  it("forgets only the matching kind+token and matching legacy keys, without resurrecting them", () => {
    saveRequestCapability("a", "hardware", "same");
    saveRequestCapability("a", "machine", "same");
    localStorage.setItem("tinkerspace.printStatus.a", "same");
    localStorage.setItem("tinkerspace.serviceStatus.b", "same");
    const result = forgetRequestCapabilities("a", { kind: "machine", token: "same", saved_at: 0 });
    expect(result.saved).toBe(true);
    expect(revealRequestCapabilities("a").records).toEqual([
      { kind: "hardware", token: "same", saved_at: expect.any(Number) },
    ]);
    expect(localStorage.getItem("tinkerspace.printStatus.a")).toBeNull();
    expect(localStorage.getItem("tinkerspace.serviceStatus.b")).toBe("same");
  });
});
