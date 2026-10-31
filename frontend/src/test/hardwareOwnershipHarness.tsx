import { onlineManager, type QueryClient } from "@tanstack/react-query";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { expect } from "vitest";
import type { HardwareRequest } from "../features/staff/panels/Queues";
import type { Makerspace } from "../features/staff/panels/shared";
import type { DirectLoan } from "../features/staff/DirectLoanList";
import type { DirectLoanMember, ProductOption } from "../features/staff/DirectLoanTypes";
import {
  chooseFile, cleanUploadSession, evidenceContract, http, json, mountStaff,
  noContent, photo, resetUploadSession, storageUrl, type HttpCall,
} from "./staffUploadHarness";

export { held, json, login, release } from "./staffUploadHarness";
export const maker: Makerspace = {
  id: 7, name: "Workshop", public_code: "WS", slug: "workshop", telegram_group_chat_id: "",
  frontend_domain: null, hidden_from_central_directory: false, enabled_modules: ["containers", "membership"],
};
export const requestA: HardwareRequest = {
  id: 1, status: "accepted", requester_username: "Borrower A", requested_for: "Repair",
  return_due_at: null, return_reminder_sent_at: null, assigned_box_id: null, assigned_box_label: null,
  items: [{ id: 21, product_id: 5, product_name: "Scope", storage_location: "Shelf A", tracking_mode: "individual",
    requires_asset_qr: true, requested_quantity: 2, accepted_quantity: 2, issued_quantity: 0,
    returned_quantity: 0, damaged_quantity: 0, missing_quantity: 0, needs_fix_quantity: 0 }],
};
// Deliberately share the line and product IDs: neither is a form-visit identity.
export const requestB: HardwareRequest = { ...requestA, id: 2, requester_username: "Borrower B" };
export const countedRequest: HardwareRequest = {
  ...requestA, items: requestA.items.map((item) => ({ ...item, requires_asset_qr: false, tracking_mode: "quantity" })),
};
export const members: DirectLoanMember[] = [
  { membership_id: 101, user_id: 11, display_name: "Borrower A", username: "borrower-a", is_walk_in: false },
  { membership_id: 102, user_id: 12, display_name: "Borrower B", username: "borrower-b", is_walk_in: false },
];
export const products: ProductOption[] = [
  { id: 5, name: "Scope", storage_location: "Shelf A", available_quantity: 8, tracking_mode: "quantity",
    is_public: true, public_self_checkout_enabled: false, is_archived: false },
  { id: 6, name: "Meter", storage_location: "Shelf B", available_quantity: 3, tracking_mode: "individual",
    is_public: true, public_self_checkout_enabled: false, is_archived: false },
];
export const containers = [
  { id: 31, code: "BOX-A", label: "Blue container", is_active: true },
  { id: 32, code: "BOX-B", label: "Green container", is_active: true },
];
export const loanA: DirectLoan = {
  id: 81, public_token: "loan-a", status: "checked_out", target_label: "Scope loan A",
  borrower_name: "Borrower A", due_at: null, issued_by: { username: "staff", role: "custom" },
  return_scan_required: true, items: [{ product_name: "Scope", quantity: 2 }],
  return_items: [
    { item_id: 91, product_name: "Scope", remaining_quantity: 2, tracking_mode: "quantity", assets: [] },
    { item_id: 92, product_name: "Meter", remaining_quantity: 1, tracking_mode: "individual", assets: [{ asset_id: 61, asset_tag: "UNIT-61" }] },
  ],
};
export const loanB: DirectLoan = { ...loanA, id: 82, public_token: "loan-b", target_label: "Scope loan B", borrower_name: "Borrower B" };
export const page = <T,>(results: T[]) => ({ count: results.length, next: null, previous: null, results });
export const asset = (tag: string) => ({ target: { type: "asset", id: tag === "UNIT-1" ? 51 : 52, asset_tag: tag, product: tag, status: "available" } });
export const box = (index = 0) => ({ target: { type: "box", ...containers[index] } });

/** All ownership, serialization and bearer decisions remain in the canonical transport. */
export function hardwareHttp(override?: (call: HttpCall) => Response | Promise<Response> | undefined,
  rows: HardwareRequest[] = [requestA, requestB], loans: DirectLoan[] = [loanA, loanB]) {
  return http((call) => {
    const response = override?.(call);
    if (response !== undefined) return response;
    if (call.path === storageUrl) return noContent();
    if (call.path.endsWith("/uploads/evidence-url")) return json(evidenceContract("PUT", 71));
    if (call.path === "/admin/qr/resolve") return json(asset(String(call.body.payload)));
    if (call.method !== "GET") return json({ id: 81 });
    const path = call.path.split("?")[0];
    if (path.endsWith("/containers")) return json(page(containers));
    if (path.endsWith("/inventory")) return json(page(products));
    if (path.endsWith("/direct-loan-members")) return json(page(members));
    if (path.endsWith("/direct-loans")) return json(page(loans));
    if (path.endsWith("/accepted-requests")) return json(page(rows.filter((row) => row.status === "accepted")));
    if (path.endsWith("/pending-requests")) return json(page(rows.filter((row) => row.status === "pending_approval")));
    if (path.endsWith("/active-loans")) return json(page(rows.filter((row) => row.status === "issued")));
    if (path.endsWith("/request-history")) return json(page([]));
    throw new Error(`Unhandled hardware fixture: ${call.method} ${call.path}`);
  });
}

let wasOnline = true;
const clients: QueryClient[] = [];
export function startHardwareTest() { wasOnline = onlineManager.isOnline(); onlineManager.setOnline(true); resetUploadSession(); scanner.current = null; }
export function endHardwareTest() {
  cleanUploadSession();
  for (const client of clients.splice(0)) client.clear();
  onlineManager.setOnline(wasOnline);
  scanner.current = null;
}
export function mountHardware(ui: ReactNode) {
  const view = mountStaff(ui);
  clients.push(view.client);
  return view;
}
/** Dropdown labels its Radix trigger; its adjacent native select owns the real change handler.
 * Drive that native control (including forced events while disabled) without replacing Dropdown.
 */
export function field(label: string | RegExp): HTMLElement {
  const control = screen.getByLabelText(label, { exact: false });
  if (control.getAttribute("role") !== "combobox") return control;
  const native = control.previousElementSibling;
  if (!(native instanceof HTMLSelectElement)) throw new Error(`No native Dropdown control for ${String(label)}`);
  return native;
}
export async function waitForChoice(label: string | RegExp, value: string) {
  await waitFor(() => {
    const control = field(label);
    if (!(control instanceof HTMLSelectElement)) throw new Error("Expected a real Dropdown");
    expect(Array.from(control.options).some((option) => option.value === value)).toBe(true);
  });
}
export function setValue(label: string | RegExp, value: string) {
  fireEvent.change(field(label), { target: { value } });
}
export async function uploadPhoto(label = "Issue photo") {
  chooseFile(label, photo);
  await screen.findByText("Photo uploaded");
}
export async function paused(client: QueryClient) {
  await waitFor(() => expect(client.getMutationCache().getAll().some((m) => m.state.isPaused)).toBe(true));
}
export async function resume(client: QueryClient) {
  await act(async () => { onlineManager.setOnline(true); await client.resumePausedMutations(); });
}
export function queueAction(person: string, action = "Issue") {
  const row = screen.getByText(person).closest("tr");
  if (!row) throw new Error(`No request row for ${person}`);
  fireEvent.click(within(row).getByRole("button", { name: action }));
}
export function dialog() { return within(screen.getByRole("dialog")); }
export async function scanAsset(payload: string) {
  setValue("Asset QR code", payload);
  fireEvent.click(dialog().getByRole("button", { name: "Add code" }));
}
export async function readyDirect() {
  await waitForChoice(/^Borrow/, "11");
  await waitForChoice("Product", "5");
  setValue(/^Borrow/, "11");
  setValue("Product", "5");
  setValue("Quantity", "2");
  setValue("Issue remark", "Click-time handout");
  await uploadPhoto();
}

export type ScannerCallbacks = { onScan: (payload: string) => void | Promise<void>; onClose: () => void };
export const scanner: { current: ScannerCallbacks | null } = { current: null };
/** Camera/provider leaf; retained callbacks intentionally remain callable after close/unmount. */
export function ScannerLeaf(props: ScannerCallbacks) {
  scanner.current = props;
  return <div data-testid="hardware-scanner"><button onClick={props.onClose}>Close native scanner</button></div>;
}
