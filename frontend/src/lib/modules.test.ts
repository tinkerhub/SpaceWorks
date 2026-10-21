import { describe, expect, it } from "vitest";

import { moduleEnabled } from "./modules";

describe("moduleEnabled", () => {
  it("fails closed when the module list is unknown", () => {
    expect(moduleEnabled(undefined, "events")).toBe(false);
    expect(moduleEnabled(null, "events")).toBe(false);
  });

  it("reads arrays and sets alike", () => {
    expect(moduleEnabled(["events"], "events")).toBe(true);
    expect(moduleEnabled(new Set(["events"]), "events")).toBe(true);
    expect(moduleEnabled([], "events")).toBe(false);
    expect(moduleEnabled(new Set(["bookings"]), "events")).toBe(false);
  });
});
