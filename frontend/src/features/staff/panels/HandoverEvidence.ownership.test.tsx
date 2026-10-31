import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AssignIssueModal } from "./QueuesAssignIssueModal";
import { ReturnRequestModal } from "./QueuesReturnRequestModal";
import type { HardwareRequest } from "./Queues";
import {
  chooseFile, cleanUploadSession, evidenceContract, held, http, json, mountStaff,
  noContent, photo, release, resetUploadSession, storageUrl,
} from "../../../test/staffUploadHarness";

beforeEach(() => { resetUploadSession(); });
afterEach(() => { cleanUploadSession(); });
const row: HardwareRequest = {
  id: 1, status: "accepted", requester_username: "A", requested_for: "Repair",
  return_due_at: null, return_reminder_sent_at: null, assigned_box_id: null, assigned_box_label: null,
  items: [{ id: 21, product_id: 5, product_name: "Scope", storage_location: "", tracking_mode: "quantity",
    requires_asset_qr: false, requested_quantity: 1, accepted_quantity: 1, issued_quantity: 0,
    returned_quantity: 0, damaged_quantity: 0, missing_quantity: 0, needs_fix_quantity: 0 }],
};
const nextRow = { ...row, id: 2, requester_username: "B" };
const issued = { ...row, status: "issued", items: row.items.map((item) => ({ ...item, issued_quantity: 1 })) };
const modal = { open: true, pending: false, error: "", makerspaceId: 7, onClose: () => {} };

it("actual unkeyed issue dialog reuse fences a held presign and requires B's own photo", async () => {
  const presignA = held<Response>(); let count = 0;
  const submit = vi.fn();
  const net = http((call) => call.path === storageUrl ? noContent()
    : call.path.endsWith("evidence-url") && ++count === 1 ? presignA.promise : json(evidenceContract("PUT", 72)));
  const view = mountStaff(<AssignIssueModal {...modal} row={row} onSubmit={submit} />);
  chooseFile("Issue photo", photo);
  await waitFor(() => expect(count).toBe(1));
  // No artificial key: React reuses the real caller and its parent evidence setter.
  view.rerender(<AssignIssueModal {...modal} row={nextRow} onSubmit={submit} />);
  await release(presignA, json(evidenceContract("PUT", 71)));
  expect(net.calls.some((call) => call.path === storageUrl)).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Issue" }));
  expect(screen.getByText("Upload an issue photo before issuing.")).toBeVisible();
  expect(submit).not.toHaveBeenCalled();
  chooseFile("Issue photo", photo);
  await screen.findByText("Photo uploaded");
  fireEvent.click(screen.getByRole("button", { name: "Issue" }));
  expect(submit).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ evidenceId: 72, boxCode: "", assetQrPayloads: [] }));
});

it.each(["success", "error"])("unkeyed return dialog rejects late A raw %s without clearing B photo or return rules", async (outcome) => {
  const rawA = held<Response>(); let uploads = 0; let presigns = 0;
  const submit = vi.fn();
  http((call) => call.path === storageUrl ? (++uploads === 1 ? rawA.promise : noContent()) : json(evidenceContract("POST", ++presigns === 1 ? 71 : 72)));
  const view = mountStaff(<ReturnRequestModal {...modal} row={issued} onSubmit={submit} />);
  chooseFile("Return photo", photo);
  await waitFor(() => expect(uploads).toBe(1));
  const rowB = { ...issued, id: 2, requester_username: "B" };
  view.rerender(<ReturnRequestModal {...modal} row={rowB} onSubmit={submit} />);
  chooseFile("Return photo", photo);
  await screen.findByText("Photo uploaded");
  await release(rawA, outcome === "success" ? noContent() : new Response(null, { status: 503 }));
  expect(screen.queryByText(/Photo upload failed/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Submit return" }));
  expect(screen.getByText("Return remark is required.")).toBeVisible();
  expect(submit).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText(/^Remark/), { target: { value: "All back intact" } });
  fireEvent.click(screen.getByRole("button", { name: "Submit return" }));
  expect(submit).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ evidenceId: 72, remark: "All back intact", boxCode: "" }));
});
