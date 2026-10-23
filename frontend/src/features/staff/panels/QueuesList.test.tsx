import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { HardwareRequest } from "./Queues";
import { RequestList } from "./QueuesList";

const row: HardwareRequest = {
  id: 7,
  status: "pending_approval",
  requester_username: "walkin_test_visitor",
  requester_display: "Test Visitor",
  requested_for: "Line-following robot",
  return_due_at: null,
  return_reminder_sent_at: null,
  items: [{
    id: 1, product_id: 3, product_name: "Arduino Uno R4", storage_location: "Electronics Bay", tracking_mode: "quantity",
    requires_asset_qr: false, requested_quantity: 2, accepted_quantity: 0, issued_quantity: 0, returned_quantity: 0,
    damaged_quantity: 0, missing_quantity: 0, needs_fix_quantity: 0,
  }],
};

function stubPhone(matches: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches, media: query, onchange: null,
    addEventListener: () => undefined, removeEventListener: () => undefined,
    addListener: () => undefined, removeListener: () => undefined, dispatchEvent: () => false,
  }));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("RequestList", () => {
  it("shows a table with the row's actions on wider screens", () => {
    stubPhone(false);
    render(<RequestList rows={[row]} label="Pending review" actions={() => <button type="button">Accept</button>} />);

    const table = screen.getByRole("table");
    expect(within(table).getByText("Arduino Uno R4")).toBeInTheDocument();
    expect(within(table).getByRole("button", { name: "Accept" })).toBeInTheDocument();
    expect(within(table).getByRole("button", { name: "Details for request #7" })).toBeInTheDocument();
  });

  it("shows one card per request on phones, with its actions under it and no table", () => {
    stubPhone(true);
    render(<RequestList rows={[row]} label="Pending review" actions={() => <button type="button">Accept</button>} />);

    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    const list = screen.getByRole("list", { name: "Pending review" });
    const card = within(list).getAllByRole("listitem")[0];
    expect(within(card).getByText("Test Visitor")).toBeInTheDocument();
    expect(within(card).getByText("Shelf: Electronics Bay")).toBeInTheDocument();
    expect(within(card).getByText("Not set")).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Accept" })).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Details for request #7" })).toBeInTheDocument();
  });
});
