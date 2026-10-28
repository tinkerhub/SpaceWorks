import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MachineType } from "../../machinesApi";
import { BuiltinTypeRow } from "./BuiltinTypeRow";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../../../lib/api", () => ({ staffRequest }));

const laser: MachineType = {
  id: 4, slug: "laser_cutter", name: "Laser Cutter", icon: "", is_builtin: true, managing_action: "", makerspace: null,
  capability_config: { metering_unit: "minutes", requires_booking: true },
  effective_config: { metering_unit: "minutes", requires_booking: true, uses_consumables: false, overridden: false },
};

function renderRow(machineType: MachineType, currency = "INR", canConfigure = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ul><BuiltinTypeRow makerspaceId={9} machineType={machineType} canConfigure={canConfigure} currency={currency} /></ul>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  staffRequest.mockReset();
  staffRequest.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path.endsWith("/settings")) return { ...laser, effective_config: { ...JSON.parse(String(init?.body)), uses_consumables: true, overridden: true } };
    return { currency: "inr", results: [{ machine_type_id: 4, rate_per_unit: "1.00", flat_fee: "0.00", payment_enabled: false, free_below_quantity: "0.00" }] };
  });
});

describe("BuiltinTypeRow", () => {
  it("lets a space manager change a built-in for this makerspace only, sending only what differs", async () => {
    renderRow(laser);
    expect(screen.getByText(/This makerspace only/)).toBeVisible();
    // Minutes types take no consumables, so the switch is not offered.
    expect(screen.queryByRole("switch", { name: /Uses consumables/ })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("combobox", { name: "Metering unit" }));
    fireEvent.click(screen.getByRole("option", { name: "Count" }));
    expect(screen.getByRole("switch", { name: /Uses consumables/ })).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Save for this makerspace" }));

    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/makerspace/9/machine-types/4/settings",
      expect.objectContaining({ method: "PUT" }),
    ));
    const call = staffRequest.mock.calls.find(([path]) => String(path).endsWith("/settings"))!;
    // The built-in's raw switch is already on, so "on" inherits it rather than overriding.
    expect(JSON.parse(String(call[1].body))).toEqual({ metering_unit: "count", requires_booking: null, uses_consumables: null });
  });

  it("sends an explicit off when a minutes built-in moves to a unit with consumables switched off", async () => {
    renderRow(laser);
    fireEvent.click(screen.getByRole("combobox", { name: "Metering unit" }));
    fireEvent.click(screen.getByRole("option", { name: "Count" }));
    fireEvent.click(screen.getByRole("switch", { name: /Uses consumables/ }));
    fireEvent.click(screen.getByRole("button", { name: "Save for this makerspace" }));

    await waitFor(() => {
      const call = staffRequest.mock.calls.find(([path]) => String(path).endsWith("/settings"));
      expect(call && JSON.parse(String(call[1].body))).toEqual({ metering_unit: "count", requires_booking: null, uses_consumables: false });
    });
  });

  it("offers a reset once overridden, and keeps a read-only row for other staff", async () => {
    renderRow({ ...laser, effective_config: { metering_unit: "count", requires_booking: true, uses_consumables: true, overridden: true } });
    expect(screen.getByText("Built-in · changed for this makerspace")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Use built-in settings" }));
    await waitFor(() => {
      const call = staffRequest.mock.calls.find(([path]) => String(path).endsWith("/settings"));
      expect(call && JSON.parse(String(call[1].body))).toEqual({ metering_unit: null, requires_booking: null, uses_consumables: null });
    });
  });

  it("hides the settings form without configure permission", () => {
    renderRow(laser, "INR", false);
    expect(screen.queryByRole("button", { name: "Save for this makerspace" })).not.toBeInTheDocument();
  });

  it("labels prices with the upper-case currency, and with no suffix until it is known", async () => {
    const { unmount } = renderRow(laser, "inr");
    expect(await screen.findByLabelText("Rate per unit (INR)")).toBeVisible();
    expect(screen.getByLabelText("Free below (min)")).toBeVisible();
    unmount();
    renderRow(laser, "");
    expect(await screen.findByLabelText("Rate per unit")).toBeVisible();
    expect(screen.queryByText(/\(Currency\)/)).not.toBeInTheDocument();
  });
});
