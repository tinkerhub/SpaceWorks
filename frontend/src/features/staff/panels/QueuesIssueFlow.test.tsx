import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Queues, type HardwareRequest } from "./Queues";
import type { Makerspace } from "./shared";

const { staffRequest, issueResult } = vi.hoisted(() => ({ staffRequest: vi.fn(), issueResult: vi.fn() }));
vi.mock("../../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../../lib/api")>("../../../lib/api");
  return { ...actual, staffRequest };
});

const makerspace: Makerspace = {
  id: 7, name: "Workshop", slug: "workshop", public_code: "workshop",
  telegram_group_chat_id: "", frontend_domain: null, hidden_from_central_directory: false,
};
const accepted: HardwareRequest = {
  id: 4, status: "accepted", requester_username: "asha", requested_for: "Debugging",
  return_due_at: null, return_reminder_sent_at: null, assigned_box_id: null, assigned_box_label: null,
  items: [{
    id: 21, product_id: 5, product_name: "Oscilloscope", storage_location: "Bench",
    tracking_mode: "quantity", requires_asset_qr: false, requested_quantity: 1, accepted_quantity: 1,
    issued_quantity: 0, returned_quantity: 0, damaged_quantity: 0, missing_quantity: 0, needs_fix_quantity: 0,
  }],
};

let queryClient: QueryClient;
let serverRow: HardwareRequest;
let issued: boolean;

beforeEach(() => {
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } });
  serverRow = { ...accepted };
  issued = false;
  issueResult.mockReset().mockResolvedValue({});
  staffRequest.mockReset().mockImplementation(async (path: string, options?: RequestInit) => {
    if (path.includes("/accepted-requests?")) {
      return { count: issued ? 0 : 1, next: null, previous: null, results: issued ? [] : [{ ...serverRow }] };
    }
    if (path.includes("/active-loans?") || path.includes("/pending-requests?")) {
      return { count: 0, next: null, previous: null, results: [] };
    }
    if (path.includes("/containers?")) return { results: [{ id: 1, code: "bin-code", label: "Kit bin" }] };
    if (path.includes("/uploads/evidence-url")) {
      return { evidence_id: 9, upload_url: "http://storage.test/evidence", fields: { key: "k" }, object_key: "k" };
    }
    if (path === "/admin/qr/resolve") return { target: { type: "asset", product: "Oscilloscope", asset_tag: "OSC-01" } };
    if (path === "/admin/requests/4/assign-box") {
      serverRow = { ...serverRow, assigned_box_id: 1, assigned_box_label: "Kit bin" };
      return serverRow;
    }
    if (path === "/admin/requests/4/issue") {
      const result = await issueResult(JSON.parse(String(options?.body)));
      issued = true;
      return result;
    }
    throw new Error(`Unexpected staff API call: ${path}`);
  });
  vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 204 })));
  vi.stubGlobal("matchMedia", (media: string) => ({
    matches: false, media, onchange: null, addEventListener() {}, removeEventListener() {},
    addListener() {}, removeListener() {}, dispatchEvent: () => false,
  }));
});

afterEach(() => {
  queryClient.clear();
  vi.unstubAllGlobals();
});

async function openIssue() {
  render(
    <QueryClientProvider client={queryClient}>
      <Queues makerspace={makerspace} guestOnly canReturnRequest canReviewRequests={false} />
    </QueryClientProvider>,
  );
  fireEvent.click(await screen.findByRole("button", { name: "Issue" }));
  return within(screen.getByRole("dialog", { name: "Issue request #4" }));
}

async function uploadPhoto() {
  const file = new File([new Uint8Array([0xff, 0xd8, 0xff])], "issue.jpg", { type: "image/jpeg" });
  fireEvent.change(screen.getByLabelText("Issue photo"), { target: { files: [file] } });
  expect(await screen.findByText("Photo uploaded")).toBeVisible();
}

async function chooseContainer() {
  fireEvent.click(await screen.findByRole("combobox", { name: "Available container" }));
  fireEvent.click(await screen.findByRole("option", { name: "Kit bin" }));
}

function handoverCalls() {
  return staffRequest.mock.calls
    .filter(([path]) => String(path).startsWith("/admin/requests/4/"))
    .map(([path, options]) => ({ path, body: JSON.parse(String(options.body)) }));
}

describe("Queues issue flow with the real handover form", () => {
  it.each([false, true])("skips assignment when no container is chosen (selected then cleared: %s)", async (toggleOff) => {
    const modal = await openIssue();
    if (toggleOff) {
      fireEvent.click(modal.getByRole("checkbox", { name: /^Use a container/ }));
      await chooseContainer();
      fireEvent.click(modal.getByRole("checkbox", { name: /^Use a container/ }));
      expect(modal.queryByLabelText("Available container")).not.toBeInTheDocument();
    }
    await uploadPhoto();
    fireEvent.change(modal.getByLabelText(/^Remark/), { target: { value: "Handed over loose." } });
    fireEvent.click(modal.getByRole("button", { name: "Issue" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(handoverCalls()).toEqual([{
      path: "/admin/requests/4/issue",
      body: { evidence_id: 9, remark: "Handed over loose.", rejects: [], asset_qr_payloads: [] },
    }]);
    expect(issueResult).toHaveBeenCalledTimes(1);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("locks a successful container assignment and preserves photo, scans and remark for issue retry", async () => {
    serverRow = { ...accepted, items: [{ ...accepted.items[0], tracking_mode: "individual", requires_asset_qr: true }] };
    issueResult.mockRejectedValueOnce(new Error("Issue temporarily unavailable."));
    const modal = await openIssue();
    fireEvent.click(modal.getByRole("checkbox", { name: /^Use a container/ }));
    await chooseContainer();
    await uploadPhoto();
    fireEvent.change(modal.getByLabelText(/^Remark/), { target: { value: "Probe included; checked at desk." } });
    fireEvent.change(modal.getByLabelText(/^Asset QR code/), { target: { value: "asset-payload" } });
    fireEvent.click(modal.getByRole("button", { name: "Add code" }));
    expect(await modal.findByText("Asset QR codes (1/1)")).toBeVisible();
    fireEvent.click(modal.getByRole("button", { name: "Issue" }));

    expect(await modal.findByText(/Container assigned, but issue failed: Issue temporarily unavailable/)).toBeVisible();
    await waitFor(() => expect(modal.getByRole("button", { name: "Issue" })).toBeEnabled());
    // Assignment also refetches the queue with a changed row. The open form must stay intact.
    await waitFor(() => expect(queryClient.getQueryData<{ results: HardwareRequest[] }>(["accepted", 7, 1, 24, ""])?.results[0].assigned_box_id).toBe(1));
    const toggle = modal.getByRole("checkbox", { name: /^Use a container/ });
    expect(toggle).toBeChecked();
    expect(toggle).toBeDisabled();
    expect(modal.getByText(/Assigned container:/)).toHaveTextContent("bin-code");
    expect(modal.queryByLabelText("Available container")).not.toBeInTheDocument();
    expect(modal.getByText("Photo uploaded")).toBeVisible();
    expect(modal.getByText("Asset QR codes (1/1)")).toBeVisible();
    expect(modal.getByRole("button", { name: "Remove Oscilloscope" })).toBeEnabled();
    expect(modal.getByLabelText(/^Remark/)).toHaveValue("Probe included; checked at desk.");
    const issueBody = {
      evidence_id: 9, remark: "Probe included; checked at desk.", rejects: [], asset_qr_payloads: ["asset-payload"],
    };
    expect(handoverCalls()).toEqual([
      { path: "/admin/requests/4/assign-box", body: { box_code: "bin-code" } },
      { path: "/admin/requests/4/issue", body: issueBody },
    ]);

    fireEvent.click(modal.getByRole("button", { name: "Issue" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(handoverCalls()).toEqual([
      { path: "/admin/requests/4/assign-box", body: { box_code: "bin-code" } },
      { path: "/admin/requests/4/issue", body: issueBody },
      { path: "/admin/requests/4/issue", body: issueBody },
    ]);
    expect(issueResult).toHaveBeenCalledTimes(2);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(staffRequest.mock.calls.filter(([path]) => String(path).includes("/uploads/evidence-url"))).toHaveLength(1);
    expect(staffRequest.mock.calls.filter(([path]) => path === "/admin/qr/resolve")).toHaveLength(1);
  });
});
