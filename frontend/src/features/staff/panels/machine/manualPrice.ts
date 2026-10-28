import { useQuery } from "@tanstack/react-query";

import type { MachineTypePricing } from "../../../../generated/api";
import { getMachineTypePricing, machineKeys } from "../../machinesApi";
import type { MachineType } from "../../machinesApi";
import { formatMoney } from "../../paymentsApi";
import type { ServiceDraft } from "./serviceDrafts";
import { unitShort } from "./servicePools";
import { effectiveConfig } from "./typeConfig";

export type ManualPrice = { currency: string; placeholder: string; hint: string | null };

/**
 * Preview of the backend's `manual_usage_price`, shown as the Price placeholder; null when
 * the type has no price set. The server recomputes it when the field is left blank, so this
 * only has to be right enough to quote. Nothing is charged: the price is just logged.
 */
export function manualUsagePrice(pricing: MachineTypePricing | undefined, unit: string, manual: ServiceDraft["manual"]): number | null {
  if (!pricing || (Number(pricing.rate_per_unit) <= 0 && Number(pricing.flat_fee) <= 0)) return null;
  const quantity = Number(unit === "minutes" ? manual.duration_minutes : manual.quantity) || 0;
  if (quantity < Number(pricing.free_below_quantity)) return 0;
  const amount = Number(pricing.rate_per_unit) * quantity + Number(pricing.flat_fee);
  return amount > 0 ? Math.round(amount * 100) / 100 : 0;
}

/** Props for a type's Manual usage Price field, from the makerspace's machine pricing. */
export function useManualPrice(makerspaceId: number, machineType: MachineType, manual: ServiceDraft["manual"]): ManualPrice {
  const pricing = useQuery({
    queryKey: machineKeys.pricing(makerspaceId),
    queryFn: () => getMachineTypePricing(makerspaceId),
  });
  // The price is a convenience on a logging form: a missing or odd pricing response must
  // degrade to "no auto price", never take the whole service console down with it.
  const results = Array.isArray(pricing.data?.results) ? pricing.data.results : [];
  const row = results.find((item) => item.machine_type_id === machineType.id);
  const unit = effectiveConfig(machineType).metering_unit;
  const amount = manualUsagePrice(row, unit, manual);
  const freeBelow = Number(row?.free_below_quantity ?? 0);
  return {
    currency: typeof pricing.data?.currency === "string" ? pricing.data.currency.toUpperCase() : "",
    // Until pricing loads, or for a type outside the actor's pricing scope (no row, yet the
    // server still prices the run), say "Auto"; never claim "Free" or "No price set" unseen.
    placeholder: amount === null ? (row ? "No price set" : "Auto") : amount ? amount.toFixed(2) : "Free",
    hint: amount !== null && freeBelow > 0 ? `Free under ${freeBelow} ${unitShort[unit] ?? unit}. Leave blank for the auto price.` : "Leave blank for the auto price.",
  };
}

/** A logged row's price in the makerspace currency ("₹12.50"), "Free", or an em dash when none was logged. */
export function manualPriceCell(price: string | null | undefined, currency: string): string {
  if (price === null || price === undefined) return "—";
  if (Number(price) === 0) return "Free";
  // Until the currency is known, show the bare amount rather than a malformed money string.
  return currency ? formatMoney(price, currency) : price;
}
