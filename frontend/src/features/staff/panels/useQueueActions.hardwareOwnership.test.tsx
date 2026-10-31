import { onlineManager } from "@tanstack/react-query";
import { act, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useQueueActions } from "./useQueueActions";
import {
  endHardwareTest, hardwareHttp, held, json, login, maker, mountHardware,
  paused, release, requestA, requestB, resume, startHardwareTest,
} from "../../../test/hardwareOwnershipHarness";

beforeEach(startHardwareTest);
afterEach(endHardwareTest);
let actions: ReturnType<typeof useQueueActions>;
function Harness() {
  actions = useQueueActions(maker);
  return <><p>{actions.acceptRow?.requester_username ?? "Closed"}</p>
    <p data-testid="pending">{String(actions.pending)}</p><p>{actions.modalError}</p></>;
}
function open(row = requestA) { act(() => { actions.openModal(actions.setAcceptRow, row); }); }
const contracts = [
  { path: "accept", body: { accepted_quantities: [{ item_id: 21, quantity: 2 }] } },
  { path: "reject", body: { reason: "Click-time reason" } },
  { path: "cancel", body: { reason: "Click-time cancellation reason" } },
  { path: "return-due", body: { return_due_at: "2026-12-01T10:00:00.000Z" } },
  { path: "return", body: { evidence_id: 71, box_code: "BOX-A", remark: "All back",
    resolutions: [{ item_id: 21, returned: 1, damaged: 1, missing: 0 }] } },
];

it.each(contracts)("$path captures the entire body before pause and blocks same-tick duplicate admission", async ({ path, body }) => {
  const net = hardwareHttp();
  const view = mountHardware(<Harness />);
  open();
  const original = structuredClone(body);
  const mutable = structuredClone(body);
  onlineManager.setOnline(false);
  act(() => {
    void actions.runAction(`/admin/requests/1/${path}`, mutable, "Saved current request", "Failed");
    void actions.runAction(`/admin/requests/1/${path}`, { unexpected: "duplicate" }, "Duplicate", "Failed");
  });
  // Simulate a parent retaining/mutating the original object while the mutation is paused.
  Object.assign(mutable, { reason: "Later reason", evidence_id: 999, remark: "Later", return_due_at: null });
  if ("accepted_quantities" in mutable) mutable.accepted_quantities![0].quantity = 99;
  if ("resolutions" in mutable) mutable.resolutions![0].returned = 99;
  await paused(view.client);
  expect(net.writes()).toHaveLength(0);
  expect(actions.editable()).toBe(false);
  await resume(view.client);
  await screen.findByText("Saved current request");
  expect(net.writes()).toHaveLength(1);
  expect(net.writes()[0]).toMatchObject({ path: `/admin/requests/1/${path}`, body: original });
  expect(screen.getByText("Closed")).toBeVisible();
});

it.each(["actor", "unmount", "visit"])("paused dispatch is denied after same-maker %s departure", async (departure) => {
  const net = hardwareHttp();
  const view = mountHardware(<Harness key="first" />);
  open();
  onlineManager.setOnline(false);
  act(() => { void actions.runAction("/admin/requests/1/accept", { accepted_quantities: [] }, "Old success", "Old failure"); });
  await paused(view.client);
  if (departure === "actor") login("B");
  view.rerender(departure === "unmount" ? <p>Left queue</p> : <Harness key="second" />);
  if (departure !== "unmount") {
    open(requestB);
    await screen.findByText("Borrower B");
  }
  await resume(view.client);
  expect(net.writes()).toHaveLength(0);
  expect(screen.queryByText(/Old success|Old failure|Request visit changed/)).not.toBeInTheDocument();
  if (departure !== "unmount") expect(actions.acceptRow?.id).toBe(2);
});

it.each(["success", "error"])("old %s and finally cannot clear, toast or release B's pending action", async (outcome) => {
  const responseA = held<Response>(); const responseB = held<Response>(); let writes = 0;
  const net = hardwareHttp((call) => call.method === "POST" ? ++writes === 1 ? responseA.promise : responseB.promise : undefined);
  const view = mountHardware(<Harness key="A" />);
  open();
  act(() => { void actions.runAction("/admin/requests/1/reject", { reason: "A reason" }, "A saved", "A failed"); });
  await waitFor(() => expect(writes).toBe(1));
  view.rerender(<Harness key="B" />);
  open(requestB);
  await screen.findByText("Borrower B");
  act(() => { void actions.runAction("/admin/requests/2/reject", { reason: "B reason" }, "B saved", "B failed"); });
  await waitFor(() => expect(writes).toBe(2));
  await release(responseA, outcome === "success" ? json({ id: 1 }) : json({ detail: "A failed" }, 409));
  expect(actions.acceptRow?.id).toBe(2);
  expect(actions.editable()).toBe(false);
  expect(screen.queryByText(/A saved|A failed/)).not.toBeInTheDocument();
  act(() => { void actions.runAction("/admin/requests/2/reject", {}, "Duplicate", "Failed"); });
  expect(net.writes()).toHaveLength(2);
  await release(responseB, json({ id: 2 }));
  await screen.findByText("B saved");
});

it("current failure remains visible after lock release and explicit retry succeeds", async () => {
  let fail = true;
  const net = hardwareHttp((call) => call.method === "POST" && fail ? json({ detail: "Request temporarily busy" }, 409) : undefined);
  mountHardware(<Harness />);
  open();
  const run = () => actions.runAction("/admin/requests/1/reject", { reason: "Keep draft" }, "Retried request", "Failed");
  act(() => { void run(); });
  await screen.findAllByText("Request temporarily busy");
  await waitFor(() => expect(actions.editable()).toBe(true));
  expect(actions.modalError).toBe("Request temporarily busy");
  expect(actions.acceptRow?.id).toBe(1);
  fail = false;
  act(() => { void run(); });
  await screen.findByText("Retried request");
  expect(net.writes()).toHaveLength(2);
});

it("assign and issue both serialize their click-time bodies before the first stage pauses", async () => {
  const net = hardwareHttp();
  const view = mountHardware(<Harness />);
  act(() => { actions.openModal(actions.setAssignIssueRow, requestA); });
  const values = { boxCode: "BOX-A", evidenceId: 71, remark: "Original issue", rejects: [{ item_id: 21, broken: 1, disposition: "needs_fix" as const }], assetQrPayloads: ["UNIT-1"] };
  onlineManager.setOnline(false);
  act(() => { void actions.submitAssignIssue(values); });
  values.boxCode = "BOX-B"; values.evidenceId = 999; values.remark = "Later issue";
  values.rejects[0].broken = 2; values.assetQrPayloads.push("LATE-UNIT");
  await paused(view.client);
  await resume(view.client);
  await screen.findByText("Request #1 issued.");
  expect(net.writes().map((call) => ({ path: call.path, body: call.body }))).toEqual([
    { path: "/admin/requests/1/assign-box", body: { box_code: "BOX-A" } },
    { path: "/admin/requests/1/issue", body: { evidence_id: 71, remark: "Original issue",
      rejects: [{ item_id: 21, broken: 1, disposition: "needs_fix" }], asset_qr_payloads: ["UNIT-1"] } },
  ]);
});

it.each(["actor", "visit"])("committed assignment after %s departure refreshes only origin containers and never issues or undoes", async (departure) => {
  const assignment = held<Response>();
  const net = hardwareHttp((call) => call.path.endsWith("/assign-box") ? assignment.promise : undefined);
  const view = mountHardware(<Harness key="A" />);
  const invalidate = vi.spyOn(view.client, "invalidateQueries");
  const clear = vi.spyOn(view.client, "clear");
  act(() => { actions.openModal(actions.setAssignIssueRow, requestA); });
  act(() => { void actions.submitAssignIssue({ boxCode: "BOX-A", evidenceId: 71, remark: "Keep", rejects: [], assetQrPayloads: ["UNIT-1", "UNIT-2"] }); });
  await waitFor(() => expect(net.calls.some((call) => call.path.endsWith("/assign-box"))).toBe(true));
  if (departure === "actor") login("B");
  view.rerender(<Harness key="B" />);
  open(requestB);
  await screen.findByText("Borrower B");
  await release(assignment, json({ id: 1, assigned_box_id: 31 }));
  await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["containers-all", 7] }));
  expect(invalidate.mock.calls.map(([filter]) => filter?.queryKey)).toEqual([["containers", 7], ["containers-all", 7]]);
  expect(clear).not.toHaveBeenCalled();
  expect(net.writes().map((call) => call.path)).toEqual(["/admin/requests/1/assign-box"]);
  expect(actions.assignedContainerCode).toBe("");
  expect(actions.acceptRow?.id).toBe(2);
  expect(screen.queryByText(/issued\.|Could not issue/)).not.toBeInTheDocument();
});
