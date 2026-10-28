import { describe, expect, it } from "vitest";

import { configFor, effectiveConfig, typePoolUnit } from "./typeConfig";

describe("effectiveConfig", () => {
  it("prefers the makerspace-resolved settings the API sends", () => {
    const laser = {
      capability_config: { metering_unit: "minutes" as const, requires_booking: true },
      effective_config: { metering_unit: "count" as const, requires_booking: false, uses_consumables: true, overridden: true },
    };
    expect(effectiveConfig(laser).metering_unit).toBe("count");
    expect(typePoolUnit(laser)).toBe("count");
  });

  it("falls back exactly like the backend resolver: weight, no booking, consumables on", () => {
    expect(effectiveConfig({ capability_config: undefined })).toEqual({
      metering_unit: "weight", requires_booking: false, uses_consumables: true, overridden: false,
    });
  });

  it("gives minutes-metered and consumables-off types no pool unit", () => {
    expect(typePoolUnit({ capability_config: { metering_unit: "minutes", requires_booking: false, uses_consumables: true } })).toBeUndefined();
    expect(typePoolUnit({ capability_config: { metering_unit: "volume", requires_booking: false, uses_consumables: false } })).toBeUndefined();
    expect(typePoolUnit({ capability_config: { metering_unit: "volume", requires_booking: false } })).toBe("milliliters");
  });

  it("fills a config-less type's editable config from its effective settings, not a hard-coded unit", () => {
    const builtin = {
      id: 1, slug: "cnc_mill", name: "CNC Mill", icon: "", is_builtin: true, managing_action: "", makerspace: null,
      effective_config: { metering_unit: "minutes" as const, requires_booking: true, uses_consumables: false, overridden: false },
    };
    expect(configFor(builtin)).toMatchObject({ metering_unit: "minutes", requires_booking: true });
  });
});
