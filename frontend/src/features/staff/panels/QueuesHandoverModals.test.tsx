import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { HardwareRequest } from "./Queues";
import { AssignIssueModal } from "./QueuesAssignIssueModal";
import { ReturnRequestModal } from "./QueuesReturnRequestModal";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../../lib/api")>("../../../lib/api");
  return { ...actual, staffRequest };
});

const item = {
  id: 21, product_id: 5, product_name: "Oscilloscope", storage_location: "", tracking_mode: "quantity",
  requires_asset_qr: false, requested_quantity: 1, accepted_quantity: 1, issued_quantity: 1,
  returned_quantity: 0, damaged_quantity: 0, missing_quantity: 0, needs_fix_quantity: 0,
};
const issued: HardwareRequest = {
  id: 4, status: "issued", requester_username: "asha", requested_for: "Debugging", return_due_at: null,
  return_reminder_sent_at: null, assigned_box_label: "Kit bin", items: [item],
};

beforeEach(() => {
  staffRequest.mockReset();
  staffRequest.mockImplementation(async (path: string) => {
    if (path.includes("/containers")) return { results: [{ id: 1, code: "bin-code", label: "Kit bin" }] };
    if (path.includes("/uploads/evidence-url")) return { evidence_id: 9, upload_url: "http://storage.test/evidence", fields: { key: "k" }, object_key: "k" };
    if (path === "/admin/qr/resolve") return { target: { type: "asset", product: "Oscilloscope", asset_tag: "OSC-02" } };
    return {};
  });
  vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 204 })));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ReturnRequestModal", () => {
  it("asks for the loan's container instead of sending a blank box code", async () => {
    const onSubmit = vi.fn();
    render(<ReturnRequestModal row={issued} open pending={false} error="" onClose={() => {}} onSubmit={onSubmit} makerspaceId={7} />);

    const file = new File([new Uint8Array([0xff, 0xd8, 0xff])], "back.jpg", { type: "image/jpeg" });
    fireEvent.change(screen.getByLabelText("Return photo"), { target: { files: [file] } });
    expect(await screen.findByText("Photo uploaded")).toBeVisible();
    fireEvent.change(screen.getByLabelText(/^Remark/), { target: { value: "All back." } });
    fireEvent.click(screen.getByRole("button", { name: "Submit return" }));

    expect(await screen.findByText("Scan or choose the loan's container before submitting.")).toBeVisible();
    expect(onSubmit).not.toHaveBeenCalled();
  });
});

describe("AssignIssueModal", () => {
  it("takes an asset code typed by a handheld scanner like a camera scan", async () => {
    const accepted: HardwareRequest = {
      ...issued, status: "accepted",
      items: [{ ...item, tracking_mode: "individual", requires_asset_qr: true, issued_quantity: 0 }],
    };
    render(<AssignIssueModal row={accepted} open pending={false} error="" onClose={() => {}} onSubmit={() => {}} makerspaceId={7} />);

    expect(screen.getByText("Asset QR codes (0/1)")).toBeVisible();
    fireEvent.change(screen.getByLabelText(/^Asset QR code/), { target: { value: "asset-payload" } });
    fireEvent.click(screen.getByRole("button", { name: "Add code" }));

    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith("/admin/qr/resolve", expect.objectContaining({ method: "POST" })));
    expect(await screen.findByText("Asset QR codes (1/1)")).toBeVisible();
    expect(screen.getByRole("button", { name: "Remove Oscilloscope" })).toBeVisible();
  });

  it("names the container step in its own words", async () => {
    render(<AssignIssueModal row={{ ...issued, status: "accepted" }} open pending={false} error="" onClose={() => {}} onSubmit={() => {}} makerspaceId={7} />);

    fireEvent.click(screen.getByRole("button", { name: "Assign + issue" }));

    expect(await screen.findByText("Scan or choose a container before issuing.")).toBeVisible();
  });
});
