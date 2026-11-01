import { describe, expect, it } from "vitest";
import type { PrinterPool } from "../../../../generated/api";
import { serviceMachine, servicePool, serviceType } from "../../../../test/staffServiceOwnershipHarness";
import type { Machine } from "../../machinesApi";
import { usablePools, type PoolUnit } from "./servicePools";

const type = serviceType("generic");
const machine = serviceMachine(type);
function pool(overrides: Partial<PrinterPool> = {}): PrinterPool {
  return { ...servicePool(type), machine_id: null, machine_type_id: type.id, ...overrides };
}

describe("automatic allocation pool eligibility", () => {
  it.each<PoolUnit>(["grams", "milliliters", "millimeters", "count"])("offers only active, positive, unbound compatible %s stock", (unit) => {
    const pools = [
      pool({ id: 31, unit }),
      pool({ id: 32, unit, machine_type_id: null, remaining_grams: "0.01" }),
      pool({ id: 33, unit, machine_id: 11, machine_type_id: null }),
      pool({ id: 34, unit, machine_type_id: 99 }),
      pool({ id: 35, unit: unit === "grams" ? "count" : "grams" }),
      pool({ id: 36, unit, is_active: false }),
      pool({ id: 37, unit, remaining_grams: "0" }),
    ];
    expect(usablePools(pools, unit, "", [machine], 1, type.id).map((item) => item.id)).toEqual([31, 32]);
  });

  it("accepts a legacy pool with no unit only for grams", () => {
    const legacy = pool({ machine_type_id: null, unit: undefined });
    expect(usablePools([legacy], "grams", "", [machine], 1, type.id)).toEqual([legacy]);
    for (const unit of ["milliliters", "millimeters", "count"] as const) {
      expect(usablePools([legacy], unit, "", [machine], 1, type.id)).toEqual([]);
    }
  });

  it.each<{ name: string; machines: Machine[] }>([
    { name: "no known machines", machines: [] },
    { name: "only another makerspace", machines: [{ ...machine, makerspace: 2 }] },
    { name: "only another type", machines: [serviceMachine(serviceType("generic", 99))] },
    { name: "maker and type matches on separate machines", machines: [
      { ...machine, makerspace: 2 }, serviceMachine(serviceType("generic", 99), 12),
    ] },
  ])("requires a known current-maker/current-type machine: $name", ({ machines }) => {
    expect(usablePools([pool()], "grams", "", machines, 1, type.id)).toEqual([]);
  });

  it.each<Machine["status"]>(["idle", "running", "reserved", "maintenance", "offline"])("does not filter the known machine by status: %s", (status) => {
    const stock = pool();
    expect(usablePools([stock], "grams", "", [{ ...machine, status }], 1, type.id)).toEqual([stock]);
  });

  it("keeps a blank manual/missing-automatic selection empty", () => {
    expect(usablePools([pool()], "grams", "", [machine], 1)).toEqual([]);
    expect(usablePools([pool()], "grams", "", [machine], 1, undefined)).toEqual([]);
    expect(usablePools([pool()], undefined, "", [machine], 1, type.id)).toEqual([]);
  });

  it.each(["999", "not-a-machine"])("never treats an unknown nonempty machine %s as automatic", (id) => {
    expect(usablePools([pool()], "grams", id, [machine], 1, type.id)).toEqual([]);
  });

  it("preserves explicit machine scope and its existing stock-state behavior", () => {
    const pools = [
      pool({ id: 31 }),
      pool({ id: 32, machine_type_id: null }),
      pool({ id: 33, machine_id: 11, machine_type_id: null }),
      pool({ id: 34, machine_id: 12, machine_type_id: null }),
      pool({ id: 35, machine_type_id: 99 }),
      pool({ id: 36, unit: "count" }),
      pool({ id: 37, is_active: false }),
      pool({ id: 38, remaining_grams: "0" }),
    ];
    // Explicit selection retains its existing compatibility behavior, even for depleted stock.
    const ids = (automaticTypeId?: number) =>
      usablePools(pools, "grams", "11", [machine], 1, automaticTypeId).map((item) => item.id);
    expect(ids()).toEqual([31, 32, 33, 37, 38]);
    expect(ids(99)).toEqual([31, 32, 33, 37, 38]);
    expect(usablePools(pools, "grams", "11", [{ ...machine, makerspace: 2 }], 1, type.id)).toEqual([]);
  });
});
