import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it } from "vitest";

import { setValue, servicePool } from "../../../test/staffServiceOwnershipHarness";
import { cleanUploadSession, http, json, resetUploadSession } from "../../../test/staffUploadHarness";
import { machineKeys } from "../machinesApi";
import { poolQueryKey } from "./machine/servicePools";
import { machineTestMakerspaces } from "./machine/machineConsoleTestUtils";
import { mountQueuePanel, queryDataReady, queueRead, queueTypes } from "./queueNavigationTestHarness";

beforeEach(() => resetUploadSession());
afterEach(() => cleanUploadSession());

const spacesWithoutPrinting = (serviceEnabled = true) => machineTestMakerspaces().map((space) => ({
  ...space, enabled_modules: (space.enabled_modules ?? []).filter((key) =>
    key !== "printing" && (serviceEnabled || key !== "machine_service")),
}));

it("keeps printer manual history and stock/price logging on equipment when printing is disabled", async () => {
  const printer = queueTypes[1];
  const stock = { ...servicePool(printer), machine_id: null, machine_type_id: printer.id };
  const net = http((call) => {
    if (call.path === "/admin/makerspaces") return json(spacesWithoutPrinting());
    if (call.path.includes("/typed-manual-usage")) return call.method === "POST" ? json({ id: 46 })
      : json([{ id: 45, metering_unit: "weight", outcome: "success", consumed_grams: "13",
        duration_minutes: 21, percent_complete: 100, price: "11.00" }]);
    if (call.path.endsWith("/consumable-pools")) return json([stock]);
    return queueRead(call);
  });
  const view = mountQueuePanel("/admin/machines/2-3d_printer", { printingEnabled: false });
  await act(async () => { await Promise.all([
    queryDataReady(view.client, ["machine-service-manual", 1, printer.id]), queryDataReady(view.client, poolQueryKey(1)),
  ]); });
  expect(screen.getByRole("heading", { name: "Manual usage" })).toBeVisible();
  expect(await screen.findByText("13g")).toBeVisible();
  expect(screen.queryByRole("heading", { name: "3D-printer queue" })).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Printer reports" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Requests" })).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("combobox", { name: "Manual usage printer" }));
  fireEvent.click(screen.getByRole("option", { name: "Machine 12" }));
  fireEvent.click(screen.getByRole("combobox", { name: "Manual usage pool" }));
  fireEvent.click(screen.getByRole("option", { name: /PLA/ }));
  setValue("Manual usage minutes", "7");
  setValue("Manual usage quantity", "3");
  setValue("Manual usage price", "9.50");
  fireEvent.click(screen.getByRole("button", { name: "Log usage" }));
  await waitFor(() => expect(net.writes()).toHaveLength(1));
  expect(net.writes()[0]).toMatchObject({ path: "/admin/makerspaces/1/machine-service/typed-manual-usage",
    body: { machine_id: 12, consumable_pool_id: 31, duration_minutes: 7, grams: "3", price: "9.50", outcome: "success" } });
  expect(await screen.findByText("Print logged", { exact: true })).toBeVisible();
  expect(net.calls.filter((call) => /\/requests\?|machine-service-report/.test(call.path))).toEqual([]);
});

it.each([{ canManage: false }, { machineServiceEnabled: false }])("keeps printer manual usage gated: %j", async (gates) => {
  const net = http((call) => call.path === "/admin/makerspaces"
    ? json(spacesWithoutPrinting(!("machineServiceEnabled" in gates) || gates.machineServiceEnabled)) : queueRead(call));
  const view = mountQueuePanel("/admin/machines/2-3d_printer", { printingEnabled: false, ...gates });
  await act(async () => { await Promise.all([
    queryDataReady(view.client, machineKeys.list(1)), queryDataReady(view.client, machineKeys.types(1)),
  ]); });
  expect(screen.queryByRole("heading", { name: "Manual usage" })).not.toBeInTheDocument();
  expect(net.calls.filter((call) => /typed-manual-usage|\/requests\?|machine-service-report/.test(call.path))).toEqual([]);
});
