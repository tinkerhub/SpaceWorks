import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MakerspaceItemCodeSettings } from "./MakerspaceItemCodeSettings";
import type { Makerspace } from "./panels/shared";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, staffRequest };
});

const makerspace = { id: 3, name: "Tinkerspace Kochi", slug: "tinkerspace-kochi", public_code: "TSER", item_code_prefix: "TK" } as Makerspace;

function renderCard() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MakerspaceItemCodeSettings makerspace={makerspace} settings={makerspace} loading={false} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  staffRequest.mockReset();
  staffRequest.mockResolvedValue({ ...makerspace, item_code_prefix: "TKO" });
});

describe("MakerspaceItemCodeSettings", () => {
  it("previews codes with the current prefix and saves a new one in capitals", async () => {
    renderCard();
    expect(screen.getByText("TK-MCU-A")).toBeVisible();
    expect(screen.getByRole("button", { name: "Save prefix" })).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Item code prefix"), { target: { value: "tk-o" } });
    expect(screen.getByText("TKO-MCU-A")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Save prefix" }));

    await waitFor(() =>
      expect(staffRequest).toHaveBeenCalledWith("/admin/makerspaces/3", { method: "PATCH", body: JSON.stringify({ item_code_prefix: "TKO" }) }),
    );
  });
});
