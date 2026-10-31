import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { paths, renderShelf } from "../../../test/needsFixShelfHarness";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../../lib/api")>("../../../lib/api");
  return { ...actual, staffRequest };
});

describe("NeedsFixShelf quantity actions", () => {
  it("uses the full shelf count only for an untouched input and enables both actions", async () => {
    const { writes } = renderShelf();
    const input = await screen.findByRole("spinbutton", { name: "Quantity for Clamps" });
    expect(input).toHaveValue(5);
    expect(input).not.toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("button", { name: "Move back to inventory" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Scrap…" })).toBeEnabled();
    expect(screen.getByText("5 to fix")).toBeInTheDocument();
    expect(writes).toEqual([]);
  });

  it("repairs exactly the typed positive quantity, clears the override and refetches shelf counts", async () => {
    const { reads, writes, client, inventoryKeys } = renderShelf();
    const input = await screen.findByRole("spinbutton", { name: "Quantity for Clamps" });
    fireEvent.change(input, { target: { value: "2" } });
    expect(input).toHaveValue(2);
    fireEvent.click(screen.getByRole("button", { name: "Move back to inventory" }));
    await waitFor(() => expect(writes).toEqual([{
      path: paths.quantityAction, method: "POST", body: JSON.stringify({ action: "repair", quantity: 2 }),
    }]));
    await waitFor(() => {
      expect(reads[paths.shelf]).toBeGreaterThanOrEqual(2);
      expect(input).toHaveValue(3);
      for (const key of inventoryKeys) expect(client.getQueryState(key)?.isInvalidated).toBe(true);
    });
    expect(screen.getByText("3 to fix")).toBeInTheDocument();
    expect(screen.getByText("5 available · 8 total")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("2 Clamps back in stock");
  });

  it("blocks repair and scrap for zero, cleared, fractional, negative, excessive and nonfinite input", async () => {
    const { writes } = renderShelf();
    const input = await screen.findByRole<HTMLInputElement>("spinbutton", { name: "Quantity for Clamps" });
    const repair = screen.getByRole("button", { name: "Move back to inventory" });
    const scrap = screen.getByRole("button", { name: "Scrap…" });
    for (const value of ["0", "", "1.5", "-1", "6", "NaN", "Infinity", "1e309"]) {
      // Start valid each time, so even consecutive values normalized to blank trigger a change.
      fireEvent.change(input, { target: { value: "2" } });
      expect(repair).toBeEnabled();
      expect(scrap).toBeEnabled();
      fireEvent.change(input, { target: { value } });
      if (["NaN", "Infinity", "1e309"].includes(value)) {
        // A real number input sanitizes nonfinite text; React receives an empty string.
        expect(input.value).toBe("");
        expect(input).toHaveValue(null);
      } else {
        expect(input.value).toBe(value);
      }
      expect(input).toHaveAttribute("aria-invalid", "true");
      expect(repair).toBeDisabled();
      expect(scrap).toBeDisabled();
      fireEvent.click(repair);
      fireEvent.click(scrap);
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
      expect(writes).toEqual([]);
    }
  });

  it("revalidates a stale scrap confirmation, then allows a valid repair after cancel", async () => {
    const { writes } = renderShelf();
    const input = await screen.findByRole("spinbutton", { name: "Quantity for Clamps" });
    fireEvent.change(input, { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Scrap…" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Scrap 2 Clamps?" });
    // Hold the actual background input while the confirmation owns focus.
    fireEvent.change(input, { target: { value: "" } });
    expect(input).toHaveValue(null);
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(dialog).toHaveAccessibleName("Scrap 0 Clamps?");
    fireEvent.click(within(dialog).getByRole("button", { name: "Scrap" }));
    expect(writes).toEqual([]);
    expect(dialog).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();

    fireEvent.change(input, { target: { value: "1" } });
    expect(screen.getByRole("button", { name: "Scrap…" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Move back to inventory" }));
    await waitFor(() => expect(writes).toEqual([{
      path: paths.quantityAction, method: "POST", body: JSON.stringify({ action: "repair", quantity: 1 }),
    }]));
    await waitFor(() => expect(input).toHaveValue(4));
    expect(screen.getByRole("status")).toHaveTextContent("1 Clamps back in stock");
  });

  it("scraps exactly the valid quantity through the real confirmation and resets after success", async () => {
    const { reads, writes } = renderShelf();
    const input = await screen.findByRole("spinbutton", { name: "Quantity for Clamps" });
    fireEvent.change(input, { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "Scrap…" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Scrap 3 Clamps?" });
    expect(within(dialog).getByText("Scrapped units are removed from inventory for good. The adjustment is logged.")).toBeInTheDocument();
    expect(writes).toEqual([]);
    fireEvent.click(within(dialog).getByRole("button", { name: "Scrap" }));
    await waitFor(() => expect(writes).toEqual([{
      path: paths.quantityAction, method: "POST", body: JSON.stringify({ action: "scrap", quantity: 3 }),
    }]));
    await waitFor(() => {
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
      expect(reads[paths.shelf]).toBeGreaterThanOrEqual(2);
      expect(input).toHaveValue(2);
    });
    expect(screen.getByText("3 available · 5 total")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("3 Clamps scrapped");
    expect(screen.getByRole("button", { name: "Move back to inventory" })).toBeEnabled();
  });
});
