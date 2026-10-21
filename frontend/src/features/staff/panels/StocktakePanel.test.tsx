import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StocktakePanel } from "./StocktakePanel";
import type { Makerspace } from "./shared";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../../lib/api")>("../../../lib/api");
  return { ...actual, staffRequest };
});

const makerspace = { id: 7, name: "Lab", public_code: "lab", slug: "lab" } as Makerspace;

const rows = [
  { id: 1, status: "completed", notes: "Mine", container: null, can_approve: false, can_apply: false },
  { id: 2, status: "completed", notes: "Theirs", container: null, can_approve: true, can_apply: false },
  { id: 3, status: "approved", notes: "Ready", container: null, can_approve: false, can_apply: true },
  { id: 4, status: "approved", notes: "Legacy", container: null, can_approve: false, can_apply: false },
];

function renderPanel() {
  staffRequest.mockImplementation(async (path: string) => {
    if (path.startsWith("/admin/makerspace/7/stocktakes")) {
      return { count: rows.length, next: null, previous: null, results: rows };
    }
    if (path.includes("/containers")) return { results: [] };
    return {};
  });
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <StocktakePanel makerspace={makerspace} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  staffRequest.mockReset();
});

describe("StocktakePanel review buttons", () => {
  it("shows Approve and Apply only where the server says the user may act", async () => {
    renderPanel();

    expect(await screen.findByText("#2")).toBeVisible();
    expect(screen.getAllByRole("button", { name: "Approve" })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "Apply" })).toHaveLength(1);
  });

  it("posts approve and apply for the rows that allow them", async () => {
    renderPanel();

    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
    await waitFor(() =>
      expect(staffRequest).toHaveBeenCalledWith("/admin/stocktakes/2/approve", expect.objectContaining({ method: "POST" })),
    );
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() =>
      expect(staffRequest).toHaveBeenCalledWith(
        "/admin/stocktakes/3/apply-adjustments",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });
});

describe("StocktakePanel start dialog", () => {
  it("starts a stocktake with the notes from the dialog", async () => {
    renderPanel();

    fireEvent.click(await screen.findByRole("button", { name: "Start stocktake" }));
    const dialog = await screen.findByRole("dialog", { name: "Start stocktake" });
    fireEvent.change(within(dialog).getByLabelText("Session notes"), { target: { value: "Shelf B audit" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Start stocktake" }));

    await waitFor(() =>
      expect(staffRequest).toHaveBeenCalledWith(
        "/admin/makerspace/7/stocktakes",
        expect.objectContaining({ method: "POST", body: JSON.stringify({ notes: "Shelf B audit", container_id: null }) }),
      ),
    );
  });
});
