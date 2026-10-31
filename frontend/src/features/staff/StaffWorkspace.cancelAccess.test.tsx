import type { ReactNode } from "react";
import { fireEvent, screen, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { StaffWorkspace } from "./StaffWorkspace";
import { getStaffAccess } from "./staffAccess";
import type { StaffAuthUser } from "../../lib/api";
import {
  endHardwareTest, hardwareHttp, maker, mountHardware, requestA, startHardwareTest,
} from "../../test/hardwareOwnershipHarness";

// Only the surrounding chrome is irrelevant here. Keep workspace, tab content,
// lazy RequestsPanel, Queues, permissions and HTTP transport real.
vi.mock("./shell/StaffShell", () => ({ StaffShell: ({ children }: { children: ReactNode }) => <main>{children}</main> }));
beforeEach(startHardwareTest);
afterEach(endHardwareTest);

const rows = [requestA,
  { ...requestA, id: 3, status: "pending_approval", requester_username: "Pending borrower" },
  { ...requestA, id: 4, status: "issued", requester_username: "Active borrower",
    items: requestA.items.map((item) => ({ ...item, issued_quantity: 2 })) },
];
function Location() { return <output aria-label="Current route">{useLocation().pathname}</output>; }
function mountWorkspace(actions: string[], superadmin = false, guestOnly = false) {
  const user: StaffAuthUser = {
    username: "custom-staff", email_verified: true, role: "custom", is_superuser: superadmin,
    must_change_password: false, makerspaces: [{
      id: maker.id, slug: maker.slug, role: null, role_id: 91, role_name: "Custom reviewer", role_slug: "reviewer",
      source: "membership", actions, can_configure_machine_types: false, is_machine_only: false,
      can_refer: false, can_verify: false, verified_at: null, referrals_enabled: false, currency: "inr",
    }],
  };
  const route = guestOnly ? "/guest-admin/requests" : "/m/workshop/admin/requests";
  const net = hardwareHttp(undefined, rows);
  mountHardware(<MemoryRouter initialEntries={[route]}><Location /><StaffWorkspace
    activeMakerspace={maker} actions={actions} isMachineOnly={false} canConfigureMachineTypes={false}
    guestOnly={guestOnly} isSuperadmin={superadmin} makerspaces={[maker]} onAuthRefresh={() => {}}
    selected={maker.id} setSelected={() => {}} setTab={() => {}} signOut={async () => {}}
    singleTenantLocked={false} user={user}
  /></MemoryRouter>);
  return { net, route };
}
function noAction(name: string | RegExp) {
  expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
}

it("reject-only custom membership reaches Requests and forwards cancellation through the real workspace chain", async () => {
  const access = getStaffAccess(["reject_request"], false, false);
  expect(access.allowedTabs).toContain("requests");
  expect(access.canCancelRequests).toBe(true);
  expect(access.canReviewRequests).toBe(false);
  const { net, route } = mountWorkspace(["reject_request"]);
  const cancel = await screen.findByRole("button", { name: "Cancel request…" });
  expect(screen.getByLabelText("Current route")).toHaveTextContent(route);
  expect(await screen.findByRole("button", { name: "Reject…" })).toBeVisible();
  for (const name of ["Accept", "Issue", "Set due", "Return"]) noAction(name);
  expect(screen.queryByRole("heading", { name: "Active loans" })).not.toBeInTheDocument();
  expect(net.calls.some((call) => call.path.includes("/active-loans"))).toBe(false);
  fireEvent.click(cancel);
  expect(screen.getByRole("alertdialog", { name: "Cancel request #1?" })).toBeVisible();
});

it("accept-only membership gets Accept and Set due but no Reject or Cancel", async () => {
  mountWorkspace(["accept_request"]);
  expect(await screen.findByRole("button", { name: "Accept" })).toBeVisible();
  await screen.findByText("Borrower A");
  expect(screen.getAllByRole("button", { name: "Set due" })).toHaveLength(2);
  noAction("Reject…"); noAction(/Cancel request/); noAction("Issue");
});

it("superadmin receives cancellation, issue, return and due controls through the same wiring", async () => {
  mountWorkspace([], true);
  expect(await screen.findByRole("button", { name: "Cancel request…" })).toBeVisible();
  expect(await screen.findByRole("button", { name: "Issue" })).toBeVisible();
  expect(await screen.findByRole("button", { name: "Return" })).toBeVisible();
  expect(await screen.findByRole("button", { name: "Accept" })).toBeVisible();
  expect(screen.getAllByRole("button", { name: "Set due" })).toHaveLength(3);
});

it("the guest surface withholds cancellation even when reject permission is supplied", async () => {
  mountWorkspace(["reject_request"], false, true);
  await screen.findByText("Borrower A");
  noAction(/Cancel request/); noAction("Reject…");
  expect(screen.queryByRole("heading", { name: "Pending review" })).not.toBeInTheDocument();
});

it("authorized handover retains Issue and Return while review and cancellation stay hidden", async () => {
  mountWorkspace(["issue_request", "return_request", "upload_evidence"]);
  expect(await screen.findByRole("button", { name: "Issue" })).toBeVisible();
  expect(await screen.findByRole("button", { name: "Return" })).toBeVisible();
  for (const name of ["Accept", "Reject…", "Set due", /Cancel request/]) noAction(name);
  expect(screen.queryByRole("heading", { name: "Pending review" })).not.toBeInTheDocument();
});

it("ISSUE alone authorizes the active list but keeps its Return control hidden", async () => {
  const { net } = mountWorkspace(["issue_request"]);
  const active = await screen.findByRole("heading", { name: "Active loans" });
  const section = active.closest("section")!;
  expect(await within(section).findByText("Active borrower")).toBeVisible();
  noAction("Return"); noAction("Set due"); noAction(/Cancel request/);
  expect(net.calls.some((call) => call.path.includes("/active-loans"))).toBe(true);
});

it("RETURN alone never fetches or renders the ISSUE-only active list", async () => {
  const { net } = mountWorkspace(["return_request"]);
  await screen.findByText("Borrower A");
  expect(screen.queryByRole("heading", { name: "Active loans" })).not.toBeInTheDocument();
  expect(net.calls.some((call) => call.path.includes("/active-loans"))).toBe(false);
  noAction("Return"); noAction("Set due"); noAction(/Cancel request/);
});
