import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, renderHook, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import type { MachineTypePricing } from "../../../../generated/api";
import type { MachineType } from "../../machinesApi";
import { formatMoney } from "../../paymentsApi";
import { ManualUsage, blankManualUsage } from "./ManualUsage";
import { manualPriceCell, manualUsagePrice, useManualPrice } from "./manualPrice";
import { blankServiceDraft } from "./serviceDrafts";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../../../lib/api", () => ({ staffRequest }));

const pricing: MachineTypePricing = {
  machine_type_id: 1, rate_per_unit: "2.00", flat_fee: "0.00", payment_enabled: false, free_below_quantity: "20.00",
};
const manual = (patch: Partial<typeof blankManualUsage>) => ({ ...blankManualUsage, ...patch });

describe("manualUsagePrice", () => {
  it("is free under the gram threshold and priced from it, payments or not", () => {
    expect(manualUsagePrice(pricing, "weight", manual({ quantity: "19.99" }))).toBe(0);
    expect(manualUsagePrice(pricing, "weight", manual({ quantity: "20" }))).toBe(40);
  });

  it("prices minutes for time-metered types, with the threshold in minutes", () => {
    const laser = { ...pricing, rate_per_unit: "1.00", flat_fee: "5.00", free_below_quantity: "10.00" };
    expect(manualUsagePrice(laser, "minutes", manual({ duration_minutes: "9" }))).toBe(0);
    expect(manualUsagePrice(laser, "minutes", manual({ duration_minutes: "12" }))).toBe(17);
  });

  it("has no price when the type has none set", () => {
    expect(manualUsagePrice({ ...pricing, rate_per_unit: "0.00" }, "weight", manual({ quantity: "50" }))).toBeNull();
    expect(manualUsagePrice(undefined, "weight", manual({ quantity: "50" }))).toBeNull();
  });

  it("formats a logged price as money, a free run, or a dash", () => {
    expect(manualPriceCell("40.00", "INR")).toBe(formatMoney("40.00", "INR"));
    expect(manualPriceCell("40.00", "inr")).toBe(formatMoney("40.00", "INR"));
    expect(manualPriceCell("40.00", "")).toBe("40.00");
    expect(manualPriceCell("0.00", "INR")).toBe("Free");
    expect(manualPriceCell(null, "INR")).toBe("—");
  });

  it("prices by the effective unit the API resolved for this makerspace", () => {
    // A built-in laser switched to count here: the quantity, not the minutes, is priced.
    const overridden = { ...pricing, free_below_quantity: "0.00" };
    expect(manualUsagePrice(overridden, "count", manual({ quantity: "3", duration_minutes: "40" }))).toBe(6);
  });
});

describe("ManualUsage price field", () => {
  const props = {
    draft: blankServiceDraft(), setDraft: () => undefined, machines: [], pools: [], machineNoun: "Printer",
    unitLabel: "grams", hasPool: true, pending: false, onSubmit: () => undefined,
    rows: [{ id: 1, outcome: "success", used: "25g", minutes: 30, price: "INR 50.00" }],
  };

  it("shows the price input and column", () => {
    render(<ManualUsage {...props} price={{ currency: "INR", placeholder: "Free", hint: "Free under 20 g." }} />);
    expect(screen.getByLabelText("Manual usage price")).toHaveAttribute("placeholder", "Free");
    expect(screen.getByText("INR 50.00")).toBeInTheDocument();
  });
});

describe("useManualPrice placeholder", () => {
  const printerType: MachineType = { id: 1, slug: "3d_printer", name: "3D printer", icon: "", is_builtin: true, managing_action: "", makerspace: null, capability_config: { metering_unit: "weight", requires_booking: false } };
  function placeholderFor(results: MachineTypePricing[], quantity: string) {
    staffRequest.mockReset();
    staffRequest.mockResolvedValue({ currency: "inr", results });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    return renderHook(() => useManualPrice(7, printerType, manual({ quantity })), { wrapper });
  }

  it("quotes the auto price, Free under the threshold, and No price set for an unpriced type", async () => {
    const priced = placeholderFor([pricing], "25");
    await waitFor(() => expect(priced.result.current.placeholder).toBe("50.00"));
    expect(priced.result.current.currency).toBe("INR");
    expect(priced.result.current.hint).toBe("Free under 20 g. Leave blank for the auto price.");
    const free = placeholderFor([pricing], "5");
    await waitFor(() => expect(free.result.current.placeholder).toBe("Free"));
    const unpriced = placeholderFor([{ ...pricing, rate_per_unit: "0.00" }], "25");
    await waitFor(() => expect(unpriced.result.current.placeholder).toBe("No price set"));
  });

  it("reads the unit from effective_config, not the built-in capability_config", async () => {
    staffRequest.mockReset();
    staffRequest.mockResolvedValue({ currency: "inr", results: [{ ...pricing, machine_type_id: 2, free_below_quantity: "0.00" }] });
    const laser: MachineType = {
      ...printerType, id: 2, slug: "laser_cutter", capability_config: { metering_unit: "minutes", requires_booking: true },
      effective_config: { metering_unit: "count", requires_booking: true, uses_consumables: true, overridden: true },
    };
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    const hook = renderHook(() => useManualPrice(7, laser, manual({ quantity: "4", duration_minutes: "90" })), { wrapper });
    await waitFor(() => expect(hook.result.current.placeholder).toBe("8.00"));
  });

  it("says Auto for a type outside the pricing scope, which the server still prices", async () => {
    const outOfScope = placeholderFor([], "25");
    await waitFor(() => expect(staffRequest).toHaveBeenCalled());
    await waitFor(() => expect(outOfScope.result.current.currency).toBe("INR"));
    expect(outOfScope.result.current.placeholder).toBe("Auto");
  });
});
