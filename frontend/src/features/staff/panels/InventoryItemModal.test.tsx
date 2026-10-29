import { useState } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ItemModal, QuantityAdjust } from "./InventoryItemModal";
import { emptyAdjust, emptyForm, payloadFromForm, type AdminProduct } from "./inventoryForm";

describe("Inventory quantities follow tracking mode", () => {
  it("hides quantities for individual creation and restores the typed quantities when switched back", () => {
    function Form() {
      const [form, setForm] = useState({ ...emptyForm, name: "Meter", total_quantity: "8", available_quantity: "6" });
      return <ItemModal title="New item" open onClose={vi.fn()} form={form} setForm={setForm}
        categories={[]} includeQuantities pending={false} onSubmit={vi.fn()} />;
    }
    render(<Form />);
    expect(screen.getByRole("spinbutton", { name: "Total quantity" })).toHaveValue(8);
    fireEvent.click(screen.getByRole("combobox", { name: "Tracking mode" }));
    fireEvent.click(within(screen.getByRole("listbox")).getByRole("option", { name: "Individual" }));
    expect(screen.queryByRole("spinbutton", { name: "Total quantity" })).not.toBeInTheDocument();
    expect(screen.queryByRole("spinbutton", { name: "Available quantity" })).not.toBeInTheDocument();
    expect(screen.getByText(/Individual items start with zero stock/)).toHaveTextContent("QR Tools");
    fireEvent.click(screen.getByRole("combobox", { name: "Tracking mode" }));
    fireEvent.click(within(screen.getByRole("listbox")).getByRole("option", { name: "Quantity" }));
    expect(screen.getByRole("spinbutton", { name: "Total quantity" })).toHaveValue(8);
    expect(screen.getByRole("spinbutton", { name: "Available quantity" })).toHaveValue(6);
  });

  it.each(["quantity", "individual"])("omits counts from %s edits and only seeds counts on create", (mode) => {
    const form = { ...emptyForm, name: "Meter", tracking_mode: mode, total_quantity: "8", available_quantity: "6" };
    const created = payloadFromForm(form, true);
    expect(created).toMatchObject({ total_quantity: mode === "individual" ? 0 : 8, available_quantity: mode === "individual" ? 0 : 6 });
    const edited = payloadFromForm(form, false);
    expect(edited).not.toHaveProperty("total_quantity");
    expect(edited).not.toHaveProperty("available_quantity");
  });

  it("shows unit workflow guidance without any manual adjustment controls", () => {
    const submit = vi.fn();
    render(<QuantityAdjust product={{ tracking_mode: "individual" } as AdminProduct}
      form={emptyAdjust} setForm={vi.fn()} pending={false} onSubmit={submit} />);
    expect(screen.getByText(/Individual counts come from unit assets/)).toHaveTextContent("QR Tools");
    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Apply adjustment" })).not.toBeInTheDocument();
    expect(submit).not.toHaveBeenCalled();
  });

  it("does not offer initial quantity fields while editing an existing item", () => {
    render(<ItemModal title="Edit item" open onClose={vi.fn()} form={{ ...emptyForm, name: "Meter" }}
      setForm={vi.fn()} categories={[]} pending={false} onSubmit={vi.fn()} />);
    expect(screen.queryByRole("spinbutton", { name: /quantity/ })).not.toBeInTheDocument();
  });
});
