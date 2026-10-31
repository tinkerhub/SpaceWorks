import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CountSection } from "./StocktakeCountSection";
import type { Makerspace } from "./shared";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

// Keep the actual queries, controls, count component and scanner (typed-code path).
vi.mock("../../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../../lib/api")>("../../../lib/api");
  return { ...actual, staffRequest };
});

const makerspace = { id: 7, name: "Lab", public_code: "lab", slug: "lab" } as Makerspace;
const quantity = { id: 11, name: "Quantity meter", tracking_mode: "quantity" };
const individual = { id: 12, name: "Unit meter", tracking_mode: "individual" };
const asset = { id: 31, asset_tag: "UNIT-31", serial_number: "", status: "available" };

beforeEach(() => {
  staffRequest.mockReset();
  staffRequest.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path === "/admin/stocktakes/9/resolve-scan") {
      const { payload } = JSON.parse(String(init?.body));
      const product = payload === "unit-product-qr" ? individual : quantity;
      return { type: "product", product_id: product.id, name: product.name };
    }
    if (path === "/admin/stocktakes/9/count-lines") return { id: 1 };
    if (path === "/admin/stocktakes/9") return { id: 9, status: "counting", lines: [] };
    if (path === "/admin/makerspace/7/inventory?page_size=1000") return { results: [quantity, individual] };
    if (path === "/admin/makerspace/7/containers?page_size=1000") return { results: [] };
    if (path === "/admin/inventory/12/assets?page_size=1000") return { results: [asset] };
    if (path === "/admin/inventory/11/assets?page_size=1000") return { results: [] };
    if (path === "/admin/inventory/12") return individual;
    if (path === "/admin/inventory/11") return quantity;
    throw new Error(`Unexpected API request: ${path}`);
  });
});

async function renderCount() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })}>
      <CountSection makerspace={makerspace} stocktakeId={9} />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByRole("combobox", { name: "Product" })).toBeEnabled());
}

async function selectOption(label: string, option: string) {
  const control = screen.getByRole("combobox", { name: label });
  await waitFor(() => expect(control).toBeEnabled());
  fireEvent.click(control);
  fireEvent.click(await screen.findByRole("option", { name: option }));
}

async function scanProduct(code: string) {
  fireEvent.click(screen.getByRole("button", { name: "Scan QR" }));
  const scanner = await screen.findByRole("dialog", { name: "QR scanner" });
  fireEvent.change(await within(scanner).findByLabelText("Type the code"), { target: { value: code } });
  fireEvent.click(within(scanner).getByRole("button", { name: "Use code" }));
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "QR scanner" })).not.toBeInTheDocument());
}

function countSubmissions() {
  return staffRequest.mock.calls
    .filter(([path]) => path === "/admin/stocktakes/9/count-lines")
    .map(([, init]) => JSON.parse(init.body));
}

describe("CountSection full-audit B unit counting", () => {
  it("hides individual products from the Product dropdown", async () => {
    await renderCount();

    fireEvent.click(screen.getByRole("combobox", { name: "Product" }));

    expect(screen.getByRole("option", { name: "Quantity meter" })).toBeVisible();
    expect(screen.queryByRole("option", { name: "Unit meter" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("option", { name: "Quantity meter" }));
    expect(screen.getByRole("button", { name: "Record count" })).toBeEnabled();
  });

  it("offers individual products in Asset mode and submits the selected physical unit", async () => {
    await renderCount();
    fireEvent.click(screen.getByRole("radio", { name: "Asset" }));
    await selectOption("Product for asset", "Unit meter");
    expect(screen.getByRole("button", { name: "Record count" })).toBeDisabled();
    await selectOption("Asset", "UNIT-31 (available)");
    fireEvent.change(screen.getByLabelText("Counted"), { target: { value: "1" } });

    fireEvent.click(screen.getByRole("button", { name: "Record count" }));

    await waitFor(() => expect(countSubmissions()).toEqual([
      { asset_id: 31, counted_quantity: 1, condition: "available", notes: "" },
    ]));
  });

  it("routes an individual product QR to Asset mode with guidance and blocks aggregate submission", async () => {
    await renderCount();
    await selectOption("Product", "Quantity meter");

    await scanProduct("unit-product-qr");

    expect(screen.getByRole("radio", { name: "Asset" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("combobox", { name: "Product for asset" })).toHaveTextContent("Unit meter");
    expect(screen.getByRole("status")).toHaveTextContent(/scan or select.*asset/i);
    expect(screen.getByRole("button", { name: "Record count" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Record count" }));
    expect(countSubmissions()).toEqual([]);

    await selectOption("Asset", "UNIT-31 (available)");
    fireEvent.change(screen.getByLabelText("Counted"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "Record count" }));
    await waitFor(() => expect(countSubmissions()).toEqual([
      { asset_id: 31, counted_quantity: 1, condition: "available", notes: "" },
    ]));
  });

  it("keeps a quantity product QR countable after switching from Asset mode", async () => {
    await renderCount();
    fireEvent.click(screen.getByRole("radio", { name: "Asset" }));
    await selectOption("Product for asset", "Unit meter");
    await selectOption("Asset", "UNIT-31 (available)");

    await scanProduct("quantity-product-qr");

    expect(screen.getByRole("radio", { name: "Product" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("combobox", { name: "Product" })).toHaveTextContent("Quantity meter");
    expect(screen.queryByRole("combobox", { name: "Asset" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Counted"), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "Record count" }));

    await waitFor(() => expect(countSubmissions()).toEqual([
      { product_id: 11, counted_quantity: 3, condition: "available", notes: "" },
    ]));
  });

  it("clears incompatible product and asset selections when toggling count mode", async () => {
    await renderCount();
    await selectOption("Product", "Quantity meter");

    fireEvent.click(screen.getByRole("radio", { name: "Asset" }));

    expect(screen.getByRole("combobox", { name: "Product for asset" })).toHaveTextContent("Select product");
    expect(screen.getByRole("combobox", { name: "Asset" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Record count" })).toBeDisabled();
    await selectOption("Product for asset", "Unit meter");
    await selectOption("Asset", "UNIT-31 (available)");
    expect(screen.getByRole("button", { name: "Record count" })).toBeEnabled();

    fireEvent.click(screen.getByRole("radio", { name: "Product" }));

    expect(screen.getByRole("combobox", { name: "Product" })).toHaveTextContent("Select product");
    expect(screen.getByRole("button", { name: "Record count" })).toBeDisabled();
    fireEvent.click(screen.getByRole("radio", { name: "Asset" }));
    expect(screen.getByRole("combobox", { name: "Product for asset" })).toHaveTextContent("Select product");
    expect(screen.getByRole("combobox", { name: "Asset" })).toHaveTextContent("Select asset");
    expect(screen.getByRole("button", { name: "Record count" })).toBeDisabled();
    expect(countSubmissions()).toEqual([]);
  });
});
