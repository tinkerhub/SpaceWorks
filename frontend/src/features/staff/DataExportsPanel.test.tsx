import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DataExportsPanel } from "./DataExportsPanel";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../lib/api", () => ({ staffRequest }));

beforeEach(() => {
  staffRequest.mockReset();
});

function renderPanel() {
  staffRequest.mockResolvedValue([]);
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <DataExportsPanel makerspaceId={7} />
    </QueryClientProvider>,
  );
}

describe("DataExportsPanel", () => {
  it("shows the intentional username disclosure before the request action", async () => {
    renderPanel();

    expect(screen.getByText(/deliberate disclosure/i)).toBeVisible();
    expect(screen.getByText(/not a migration backup/i)).toBeVisible();
    // True for every access mode: a check-in site has borrowers and staff, not members, and
    // the audit log does show a numeric actor id.
    expect(screen.getByText("It does contain personal contact details.")).toBeVisible();
    expect(screen.queryByText(/member/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/omits the actor/i)).not.toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Request redacted export" })).toBeEnabled();
  });

  it("requests only REDACTED fidelity", async () => {
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "Request redacted export" }));

    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/makerspace/7/data-exports",
      { method: "POST", body: JSON.stringify({ fidelity: "REDACTED" }) },
    ));
  });
});
