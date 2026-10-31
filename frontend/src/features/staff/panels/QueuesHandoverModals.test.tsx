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
  return_reminder_sent_at: null, assigned_box_id: 1, assigned_box_label: "Kit bin", items: [item],
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

const containerless = { ...issued, assigned_box_id: null, assigned_box_label: null };
const acceptedWithoutContainer = { ...containerless, status: "accepted" };

async function uploadPhoto(label: string) {
  const file = new File([new Uint8Array([0xff, 0xd8, 0xff])], "handover.jpg", { type: "image/jpeg" });
  fireEvent.change(screen.getByLabelText(label), { target: { files: [file] } });
  expect(await screen.findByText("Photo uploaded")).toBeVisible();
}

async function chooseOption(label: string, name: string) {
  fireEvent.click(await screen.findByRole("combobox", { name: label }));
  fireEvent.click(await screen.findByRole("option", { name }));
}

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

  it("hides the container for a containerless return but requires photo and remark before submitting outcomes", async () => {
    const onSubmit = vi.fn();
    render(<ReturnRequestModal row={containerless} open pending={false} error="" onClose={() => {}} onSubmit={onSubmit} makerspaceId={7} />);

    expect(screen.queryByText("Container")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Scan" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Submit return" }));
    expect(screen.getByText("Upload a return photo before submitting.")).toBeVisible();
    expect(onSubmit).not.toHaveBeenCalled();
    await uploadPhoto("Return photo");
    fireEvent.change(screen.getByLabelText(/^Remark/), { target: { value: "   " } });
    fireEvent.click(screen.getByRole("button", { name: "Submit return" }));
    expect(screen.getByText("Return remark is required.")).toBeVisible();
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText(/^Remark/), { target: { value: "  Cracked casing.  " } });
    fireEvent.change(screen.getByLabelText("Returned"), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText("Damaged"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit return" }));

    expect(onSubmit).toHaveBeenCalledExactlyOnceWith({
      evidenceId: 9, boxCode: "", remark: "Cracked casing.",
      resolutions: [{ item_id: 21, returned: 0, damaged: 1, missing: 0 }],
    });
  });

  it("submits exact individual outcomes without a container, leaving pending units on loan", async () => {
    const onSubmit = vi.fn();
    const row = { ...containerless, items: [{
      ...item, tracking_mode: "individual", requires_asset_qr: true, issued_quantity: 2,
      issued_assets: [{ asset_id: 31, asset_tag: "OSC-01", serial_number: "" }, { asset_id: 32, asset_tag: "OSC-02", serial_number: "" }],
    }] };
    render(<ReturnRequestModal row={row} open pending={false} error="" onClose={() => {}} onSubmit={onSubmit} makerspaceId={7} />);
    await uploadPhoto("Return photo");
    fireEvent.change(screen.getByLabelText(/^Remark/), { target: { value: "One damaged, one still out." } });
    await chooseOption("OSC-01", "Damaged");
    await chooseOption("OSC-02", "Not returned now");
    fireEvent.click(screen.getByRole("button", { name: "Submit return" }));

    expect(onSubmit).toHaveBeenCalledExactlyOnceWith({
      evidenceId: 9, boxCode: "", remark: "One damaged, one still out.",
      resolutions: [{ item_id: 21, returned: 0, damaged: 1, missing: 0, assets: [{ asset_id: 31, outcome: "damaged" }] }],
    });
  });

  it("still requires a container code when the assigned container has an empty label", async () => {
    const onSubmit = vi.fn();
    render(<ReturnRequestModal row={{ ...issued, assigned_box_label: "" }} open pending={false} error="" onClose={() => {}} onSubmit={onSubmit} makerspaceId={7} />);
    await uploadPhoto("Return photo");
    fireEvent.change(screen.getByLabelText(/^Remark/), { target: { value: "All back." } });
    fireEvent.click(screen.getByRole("button", { name: "Submit return" }));
    expect(screen.getByText("Scan or choose the loan's container before submitting.")).toBeVisible();
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

    fireEvent.click(screen.getByRole("button", { name: "Issue" }));

    expect(await screen.findByText("Scan or choose a container before issuing.")).toBeVisible();
  });

  it("issues without a container only after uploading the mandatory photo", async () => {
    const onSubmit = vi.fn();
    render(<AssignIssueModal row={acceptedWithoutContainer} open pending={false} error="" onClose={() => {}} onSubmit={onSubmit} makerspaceId={7} />);
    expect(screen.getByRole("checkbox", { name: /^Use a container/ })).not.toBeChecked();
    expect(screen.queryByText("Container")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Issue" }));
    expect(screen.getByText("Upload an issue photo before issuing.")).toBeVisible();
    expect(onSubmit).not.toHaveBeenCalled();
    await uploadPhoto("Issue photo");
    fireEvent.click(screen.getByRole("button", { name: "Issue" }));
    expect(onSubmit).toHaveBeenCalledExactlyOnceWith({
      boxCode: "", evidenceId: 9, remark: "Issued from staff app.", rejects: [], assetQrPayloads: [],
    });
  });

  it("requires a code when staff opt into a container", async () => {
    const onSubmit = vi.fn();
    render(<AssignIssueModal row={acceptedWithoutContainer} open pending={false} error="" onClose={() => {}} onSubmit={onSubmit} makerspaceId={7} />);
    await uploadPhoto("Issue photo");
    fireEvent.click(screen.getByRole("checkbox", { name: /^Use a container/ }));
    fireEvent.click(screen.getByRole("button", { name: "Issue" }));
    expect(screen.getByText("Scan or choose a container before issuing.")).toBeVisible();
    expect(onSubmit).not.toHaveBeenCalled();
    await chooseOption("Available container", "Kit bin");
    fireEvent.click(screen.getByRole("button", { name: "Issue" }));
    expect(onSubmit).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ boxCode: "bin-code", evidenceId: 9 }));
  });

  it("does not leak the selected code after the optional container is toggled off", async () => {
    const onSubmit = vi.fn();
    render(<AssignIssueModal row={acceptedWithoutContainer} open pending={false} error="" onClose={() => {}} onSubmit={onSubmit} makerspaceId={7} />);
    fireEvent.click(screen.getByRole("checkbox", { name: /^Use a container/ }));
    await chooseOption("Available container", "Kit bin");
    fireEvent.click(screen.getByRole("checkbox", { name: /^Use a container/ }));
    expect(screen.queryByLabelText("Available container")).not.toBeInTheDocument();
    await uploadPhoto("Issue photo");
    fireEvent.click(screen.getByRole("button", { name: "Issue" }));
    expect(onSubmit).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ boxCode: "", evidenceId: 9 }));
  });

  it("keeps the individual scan requirement on the containerless path", async () => {
    const onSubmit = vi.fn();
    const row = { ...acceptedWithoutContainer, items: [{ ...item, tracking_mode: "individual", requires_asset_qr: true }] };
    render(<AssignIssueModal row={row} open pending={false} error="" onClose={() => {}} onSubmit={onSubmit} makerspaceId={7} />);
    await uploadPhoto("Issue photo");
    fireEvent.click(screen.getByRole("button", { name: "Issue" }));
    expect(screen.getByText("Scan exactly 1 asset QR code(s) for the individually-tracked items (scanned 0).")).toBeVisible();
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText(/^Asset QR code/), { target: { value: "asset-payload" } });
    fireEvent.click(screen.getByRole("button", { name: "Add code" }));
    expect(await screen.findByText("Asset QR codes (1/1)")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Issue" }));
    expect(onSubmit).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ boxCode: "", evidenceId: 9, assetQrPayloads: ["asset-payload"] }));
  });

  it("cannot opt out of an assigned container even when its label is empty", async () => {
    const onSubmit = vi.fn();
    render(<AssignIssueModal row={{ ...acceptedWithoutContainer, assigned_box_id: 1, assigned_box_label: "" }} open pending={false} error="" onClose={() => {}} onSubmit={onSubmit} makerspaceId={7} />);
    const toggle = screen.getByRole("checkbox", { name: /^Use a container/ });
    expect(toggle).toBeChecked();
    expect(toggle).toBeDisabled();
    await uploadPhoto("Issue photo");
    fireEvent.click(screen.getByRole("button", { name: "Issue" }));
    expect(screen.getByText("Scan or choose a container before issuing.")).toBeVisible();
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
