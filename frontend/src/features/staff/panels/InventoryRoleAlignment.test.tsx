import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../../lib/api")>("../../../lib/api");
  return { ...actual, staffRequest };
});

import { Inventory } from "./Inventory";
import { Queues } from "./Queues";
import type { Makerspace } from "./shared";

const CORE = ["public_inventory", "request_workflow", "staff_admin", "scanner", "qr_management", "evidence_uploads"];

const product = {
  id: 3, name: "Soldering iron", category: null, total_quantity: 4, available_quantity: 2,
  issued_quantity: 2, damaged_quantity: 0, lost_quantity: 0, description: "", tracking_mode: "quantity",
  is_public: true, public_self_checkout_enabled: false, is_archived: false, image_url: null,
  reserved_quantity: 0, needs_fix_quantity: 0, storage_location: "Shelf B3", show_public_count: false,
  public_availability_mode: "status_only",
};

const loan = {
  id: 41, status: "issued", requester_name: "Ada", items: [], created_at: "2026-10-01T10:00:00Z",
  issued_quantity: 1, return_due_at: null,
};

function space(modules: string[]): Makerspace {
  return {
    id: 7, name: "Forge", public_code: "forge", slug: "forge", telegram_group_chat_id: "",
    frontend_domain: null, hidden_from_central_directory: false, enabled_modules: modules,
  };
}

function wrap(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

beforeEach(() => {
  staffRequest.mockReset();
  staffRequest.mockImplementation((path: string) => {
    if (path.includes("/inventory?")) return Promise.resolve({ results: [product] });
    if (path.includes("/active-loans")) return Promise.resolve({ count: 1, results: [loan] });
    return Promise.resolve({ count: 0, results: [] });
  });
});

describe("Inventory honours canEditInventory", () => {
  it("gives a view-only role a read-only panel", async () => {
    wrap(<Inventory makerspace={space(CORE)} canEditInventory={false} />);
    const row = (await screen.findByText("Soldering iron")).closest("tr") as HTMLElement;
    expect(within(row).getByRole("button", { name: "View" })).toBeInTheDocument();
    for (const name of ["Edit", "To Fix", "Archive…"]) {
      expect(within(row).queryByRole("button", { name })).not.toBeInTheDocument();
    }
    for (const name of ["Add item", "Enable QR", "Disable QR", "Export CSV", "Export XLSX"]) {
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    }

    fireEvent.click(within(row).getByRole("button", { name: "View" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText("Name")).toBeDisabled();
    expect(within(dialog).queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
    expect(within(dialog).queryByText("Adjust quantities")).not.toBeInTheDocument();
  });

  it("keeps every control for an inventory editor", async () => {
    wrap(<Inventory makerspace={space(CORE)} canEditInventory />);
    const row = (await screen.findByText("Soldering iron")).closest("tr") as HTMLElement;
    for (const name of ["Edit", "To Fix", "Archive…"]) {
      expect(within(row).getByRole("button", { name })).toBeInTheDocument();
    }
    expect(screen.getByRole("button", { name: "Add item" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Export CSV" })).toBeInTheDocument();
  });

  it("shows To Buy only when procurement is on", async () => {
    const view = wrap(<Inventory makerspace={space(CORE)} canEditInventory canUseToBuy />);
    const row = (await screen.findByText("Soldering iron")).closest("tr") as HTMLElement;
    expect(within(row).queryByRole("button", { name: "To Buy" })).not.toBeInTheDocument();
    view.unmount();

    wrap(<Inventory makerspace={space([...CORE, "procurement"])} canEditInventory canUseToBuy />);
    const enabledRow = (await screen.findByText("Soldering iron")).closest("tr") as HTMLElement;
    expect(within(enabledRow).getByRole("button", { name: "To Buy" })).toBeInTheDocument();
  });
});

describe("request queues on the handover surface", () => {
  it("gives a handover role Active loans with Return and no Set due", async () => {
    wrap(<Queues makerspace={space(CORE)} guestOnly canIssueRequest canReturnRequest canReviewRequests={false} />);
    expect(await screen.findByRole("heading", { name: "Active loans" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Return" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Set due" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Pending review" })).not.toBeInTheDocument();
  });

  it("hides Active loans from a return-only handover role without issue authority", () => {
    wrap(<Queues makerspace={space(CORE)} guestOnly canReturnRequest canReviewRequests={false} />);
    expect(screen.queryByRole("heading", { name: "Active loans" })).not.toBeInTheDocument();
    expect(staffRequest).not.toHaveBeenCalledWith(expect.stringContaining("/active-loans"));
  });
});
