import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  individualItem, maintenanceAsset, paths, quantityItem, renderShelf, space,
} from "../../../test/needsFixShelfHarness";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../../lib/api")>("../../../lib/api");
  return { ...actual, staffRequest };
});

describe("NeedsFixShelf individual units", () => {
  it("keeps aggregate controls on quantity rows and never offers them on individual rows", async () => {
    const { reads, writes } = renderShelf({ items: [individualItem, quantityItem] });
    const individual = within(await screen.findByRole("row", { name: /Tagged drill/ }));
    expect(individual.getByText("Per unit")).toBeInTheDocument();
    expect(individual.getByRole("button", { name: "Manage units" })).toBeEnabled();
    expect(individual.queryByRole("spinbutton")).not.toBeInTheDocument();
    expect(individual.queryByRole("button", { name: "Move back to inventory" })).not.toBeInTheDocument();
    expect(individual.queryByRole("button", { name: /Scrap/ })).not.toBeInTheDocument();

    const quantity = within(screen.getByRole("row", { name: /Clamps/ }));
    expect(quantity.getByRole("spinbutton", { name: "Quantity for Clamps" })).toHaveValue(5);
    expect(quantity.getByRole("button", { name: "Move back to inventory" })).toBeEnabled();
    expect(quantity.getByRole("button", { name: "Scrap…" })).toBeEnabled();
    expect(reads).toEqual({ [paths.shelf]: 1 });
    expect(writes).toEqual([]);
  });

  it("opens the real scoped unit list, repairs its maintenance unit, refreshes views and closes normally", async () => {
    const { client, reads, writes, inventoryKeys, request } = renderShelf({ items: [individualItem] });
    for (const key of inventoryKeys) expect(client.getQueryState(key)?.isInvalidated).toBe(false);
    fireEvent.click(await screen.findByRole("button", { name: "Manage units" }));
    const dialog = await screen.findByRole("dialog", { name: "Manage units · Tagged drill" });
    const pane = within(dialog);
    expect(await pane.findByText(maintenanceAsset.asset_tag)).toBeInTheDocument();
    expect(pane.getByText("Maintenance")).toBeInTheDocument();
    expect(pane.getByText("No QR linked")).toBeInTheDocument();
    expect(request).toHaveBeenCalledWith(paths.assets);
    await waitFor(() => expect(request).toHaveBeenCalledWith(paths.containers));
    expect(pane.queryByRole("button", { name: /Scrap/ })).not.toBeInTheDocument();

    fireEvent.click(pane.getByRole("button", { name: "Move back to inventory" }));
    await waitFor(() => expect(writes).toEqual([{
      path: paths.unitRepair, method: "POST", body: JSON.stringify({ action: "repair" }),
    }]));
    expect(request).toHaveBeenCalledWith(paths.unitRepair, {
      method: "POST", body: JSON.stringify({ action: "repair" }),
    });
    await waitFor(() => {
      expect(reads[paths.assets]).toBeGreaterThanOrEqual(2);
      expect(reads[paths.shelf]).toBeGreaterThanOrEqual(2);
      for (const key of inventoryKeys) expect(client.getQueryState(key)?.isInvalidated).toBe(true);
    });
    expect(await pane.findByText("Available")).toBeInTheDocument();
    expect(await screen.findByText("Nothing on the shelf")).toBeInTheDocument();
    expect(screen.queryByRole("row", { name: /Tagged drill/ })).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("DRILL-901 is back in inventory");
    expect(pane.queryByRole("button", { name: "Move back to inventory" })).not.toBeInTheDocument();
    // The only write above is asset-scoped; the product aggregate route is never used.
    fireEvent.click(pane.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Individual assets" })).not.toBeInTheDocument();
  });

  it("disables management with a reason when asset_units is off without mounting or fetching the pane", async () => {
    const { reads, writes, client } = renderShelf({ items: [individualItem], modules: ["containers"] });
    const manage = await screen.findByRole("button", { name: "Manage units" });
    expect(manage).toBeDisabled();
    expect(screen.getByText("Unit management is unavailable because the asset units module is disabled.")).toBeInTheDocument();
    fireEvent.click(manage);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Individual assets" })).not.toBeInTheDocument();
    expect(client.getQueryState(["inventory-assets", individualItem.id])).toBeUndefined();
    expect(client.getQueryState(["containers-all", space.id])).toBeUndefined();
    expect(reads).toEqual({ [paths.shelf]: 1 });
    expect(writes).toEqual([]);
  });

  it("unmounts an open unit pane when asset_units is disabled", async () => {
    const { client, reads, writes, setModules } = renderShelf({
      items: [individualItem], modules: ["asset_units"],
    });
    fireEvent.click(await screen.findByRole("button", { name: "Manage units" }));
    const pane = within(await screen.findByRole("dialog", { name: "Manage units · Tagged drill" }));
    await pane.findByText(maintenanceAsset.asset_tag);
    expect(reads[paths.containers]).toBeUndefined();
    const before = { ...reads };
    setModules([]);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Individual assets" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Manage units" })).toBeDisabled();
    expect(client.getQueryCache().find({ queryKey: ["inventory-assets", individualItem.id] })?.getObserversCount()).toBe(0);
    expect(reads).toEqual(before);
    expect(writes).toEqual([]);
  });
});
