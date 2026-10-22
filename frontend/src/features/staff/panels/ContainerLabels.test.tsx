import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ContainerDetail } from "./ContainersPanelDetail";
import { labelForContainer } from "./StockTransferForm";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../../lib/api")>("../../../lib/api");
  return { ...actual, staffRequest };
});

function renderDetail(qrCodeId: number | null) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ContainerDetail container={{ id: 3, code: "fef0cfad", label: "Kit bin", location: "Shelf C2", qr_code_id: qrCodeId }} canEditInventory />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  staffRequest.mockReset();
  staffRequest.mockImplementation(async (path: string) => {
    if (path === "/admin/qr/12/print") return { payload: "fef0cfad", svg: "<svg xmlns='http://www.w3.org/2000/svg'/>" };
    if (path.endsWith("/contents")) return { products: [], assets: [], children: [] };
    return {};
  });
});

describe("container QR label", () => {
  it("shows the label staff scan at issue and return", async () => {
    renderDetail(12);

    expect(await screen.findByRole("img", { name: "Kit bin QR" })).toBeVisible();
  });

  it("says plainly when a container has no QR", () => {
    renderDetail(null);

    expect(screen.getByText(/has no QR label/)).toBeVisible();
  });
});

describe("labelForContainer", () => {
  it("leads with the name, not the opaque code", () => {
    expect(labelForContainer({ id: 1, code: "6429b6d8", label: "Starter Inventory", location: "Room A12" })).toBe("Starter Inventory · Room A12");
    expect(labelForContainer({ id: 2, code: "abc", label: "" })).toBe("abc");
  });
});
