import type { EffectiveTypeConfig, MachineType, MachineTypeCapabilityConfig, MeteringUnit } from "../../machinesApi";
import { poolUnits, type PoolUnit } from "./servicePools";

const METERING_UNITS: MeteringUnit[] = ["weight", "volume", "length", "count", "minutes"];

/**
 * A type's settings as they apply in this makerspace. The API resolves them (`effective_config`,
 * built-in overrides included); this is the one place the console reads them, so no component
 * keeps its own fallback unit. The local fallback mirrors the backend resolver
 * (`type_settings.settings_from_config`) for a type object that predates the field.
 */
export function effectiveConfig(machineType: Pick<MachineType, "capability_config" | "effective_config"> | undefined): EffectiveTypeConfig {
  if (machineType?.effective_config) return machineType.effective_config;
  const config = machineType?.capability_config;
  const metering_unit = config && METERING_UNITS.includes(config.metering_unit) ? config.metering_unit : "weight";
  return {
    metering_unit,
    requires_booking: config?.requires_booking === true,
    uses_consumables: metering_unit !== "minutes" && config?.uses_consumables !== false,
    overridden: false,
  };
}

/** The pool unit a type's stock is kept in, or undefined when the type takes no consumables. */
export function typePoolUnit(machineType: Pick<MachineType, "capability_config" | "effective_config"> | undefined): PoolUnit | undefined {
  const config = effectiveConfig(machineType);
  return config.uses_consumables ? poolUnits[config.metering_unit] : undefined;
}

/** A custom type's editable config, with its effective unit/booking/consumables filled in. */
export function configFor(machineType: MachineType): MachineTypeCapabilityConfig {
  const config = machineType.capability_config;
  if (config && METERING_UNITS.includes(config.metering_unit)) return config;
  const { metering_unit, requires_booking, uses_consumables } = effectiveConfig(machineType);
  return { ...config, metering_unit, requires_booking, uses_consumables };
}
