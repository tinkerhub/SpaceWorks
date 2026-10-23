import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Categories } from "./Categories";
import type { Makerspace } from "./shared";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../../lib/api")>("../../../lib/api");
  return { ...actual, staffRequest };
});

const makerspace = { id: 7, name: "Tinkerspace Calicut", slug: "tinkerspace-calicut", public_code: "TSCL", item_code_prefix: "TC" } as Makerspace;
const mcu = { id: 1, makerspace: 7, name: "Microcontrollers & Computing Boards", slug: "microcontrollers-computing-boards", code: "MCU", display_order: 0, icon: "", product_count: 2, created_at: "", updated_at: "" };
const sbcs = { ...mcu, id: 2, name: "SBCs", slug: "sbcs", code: "", product_count: 0 };

function renderPanel() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <Categories makerspace={makerspace} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  staffRequest.mockReset();
  staffRequest.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path.endsWith("/categories") && !init) return [mcu, sbcs];
    return {};
  });
});

describe("Categories", () => {
  it("shows each category's code and the classification guide with this makerspace's prefix", async () => {
    renderPanel();

    const sbcsRow = (await screen.findByText("SBCs")).closest("tr")!;
    const mcuRow = screen.getByText("Microcontrollers & Computing Boards", { selector: "span" }).closest("tr")!;
    expect(within(mcuRow).getByText("MCU")).toBeVisible();
    expect(within(sbcsRow).getAllByText("None").length).toBe(2); // no code, no icon
    expect(screen.getByRole("heading", { name: "Classification guide" })).toBeVisible();
    expect(screen.getAllByText("TC-MCU-A").length).toBeGreaterThan(0);
    expect(screen.getByText("Motor Drivers & Motion Control")).toBeInTheDocument();
    expect(screen.getByText(/ESP32-CAM:/)).toBeInTheDocument();
  });

  it("sends the code in capitals when adding a category", async () => {
    renderPanel();
    await screen.findAllByText("MCU");

    fireEvent.change(screen.getByLabelText(/^Code/), { target: { value: "tls" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Hand tools" } });
    fireEvent.click(screen.getByRole("button", { name: "Add category" }));

    await waitFor(() =>
      expect(staffRequest).toHaveBeenCalledWith(
        "/admin/makerspace/7/categories",
        expect.objectContaining({ method: "POST", body: expect.stringContaining('"code":"TLS"') }),
      ),
    );
  });
});
