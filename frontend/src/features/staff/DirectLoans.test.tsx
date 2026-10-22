import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DirectLoans } from "./DirectLoans";
import type { Makerspace } from "./panels/shared";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, staffRequest };
});

const CORE = ["public_inventory", "request_workflow", "staff_admin", "scanner", "evidence_uploads", "qr_management", "guest_handover"];
const loan = {
  id: 3, public_token: "t", status: "checked_out", target_label: "Soldering Station", due_at: null,
  issued_by: { username: "desk", role: "custom" }, borrower_name: "Ravi Kumar",
  items: [{ product_name: "Soldering Station", quantity: 1 }],
};

function renderPanel(modules: string[]) {
  const makerspace = { id: 7, name: "Lab", public_code: "lab", slug: "lab", enabled_modules: modules } as Makerspace;
  staffRequest.mockImplementation(async (path: string) => {
    if (path.includes("/direct-loan-members")) return { results: [{ membership_id: 1, user_id: 11, display_name: "Ravi Kumar", username: "walkin_ravi", is_walk_in: true }] };
    if (path.includes("/direct-loans")) return { count: 1, next: null, previous: null, results: [loan] };
    if (path.includes("claim-codes")) return [];
    return { results: [] };
  });
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <DirectLoans makerspace={makerspace} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  staffRequest.mockReset();
});

describe("DirectLoans without the membership modules", () => {
  it("names a borrower, not a member, and offers no waiver or claim codes", async () => {
    renderPanel(CORE);

    expect(await screen.findByText("Lend tools to someone at the desk, with a photo of what went out.")).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Borrower" })).toBeVisible();
    expect(screen.queryByText("Borrowing member")).toBeNull();
    expect(screen.queryByText("Member claim code")).toBeNull();
    expect(screen.queryByRole("button", { name: /witnessed waiver/i })).toBeNull();
    expect(staffRequest.mock.calls.some(([path]) => String(path).includes("claim"))).toBe(false);
  });

  it("shows who holds each open handout", async () => {
    renderPanel(CORE);

    const header = await screen.findByRole("columnheader", { name: "Borrower" });
    const table = header.closest("table") as HTMLElement;
    expect(await within(table).findByText("Ravi Kumar")).toBeVisible();
  });
});

describe("DirectLoans with the membership modules", () => {
  it("keeps the member wording and the claim-code card", async () => {
    renderPanel([...CORE, "membership", "member_accounts"]);

    expect(await screen.findByText("Borrowing member")).toBeVisible();
    expect(screen.getByText("Member claim code")).toBeVisible();
  });
});
