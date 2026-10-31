import { onlineManager } from "@tanstack/react-query";
import { act, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useQueueActions } from "./useQueueActions";
import {
  endHardwareTest, hardwareHttp, held, json, maker, mountHardware,
  paused, release, requestA, requestB, resume, startHardwareTest,
} from "../../../test/hardwareOwnershipHarness";

beforeEach(startHardwareTest);
afterEach(endHardwareTest);
let actions: ReturnType<typeof useQueueActions>;
function Harness() {
  actions = useQueueActions(maker);
  return <p>{actions.cancelRow?.requester_username ?? "Closed"}</p>;
}

it("queued cancellation belongs to one request visit, including A → B → A without remounting", async () => {
  const net = hardwareHttp();
  const view = mountHardware(<Harness />);
  act(() => { actions.openModal(actions.setCancelRow, requestA); });
  onlineManager.setOnline(false);
  act(() => { void actions.runAction("/admin/requests/1/cancel", { reason: "First A visit" }, "Departed saved", "Departed failed"); });
  await paused(view.client);
  act(() => { actions.setCancelRow(requestB); });
  await screen.findByText("Borrower B");
  act(() => { actions.setCancelRow(requestA); });
  await screen.findByText("Borrower A");
  await resume(view.client);
  expect(net.writes()).toHaveLength(0);
  expect(actions.cancelRow?.id).toBe(1);
  expect(actions.editable()).toBe(true);
  expect(screen.queryByText(/Departed saved|Departed failed|Request visit changed/)).not.toBeInTheDocument();
});

it.each(["success", "error"])("cancel row identity fences old %s without a parent remount", async (outcome) => {
  const first = held<Response>(); const second = held<Response>(); let posts = 0;
  const net = hardwareHttp((call) => call.method === "POST" ? (++posts === 1 ? first.promise : second.promise) : undefined);
  const view = mountHardware(<Harness />);
  const invalidate = vi.spyOn(view.client, "invalidateQueries");
  act(() => { actions.openModal(actions.setCancelRow, requestA); });
  const departedRun = actions.runAction;
  act(() => { void actions.runAction("/admin/requests/1/cancel", { reason: "A reason" }, "A cancelled", "A failed"); });
  await waitFor(() => expect(net.writes()).toHaveLength(1));
  // Simulate row replacement by the owning view: product/line IDs remain identical.
  act(() => { actions.setCancelRow(requestB); });
  await screen.findByText("Borrower B");
  act(() => { void departedRun("/admin/requests/1/cancel", { reason: "Stale callback" }, "Stale", "Failed"); });
  expect(net.writes()).toHaveLength(1);
  act(() => { void actions.runAction("/admin/requests/2/cancel", { reason: "B reason" }, "B cancelled", "B failed"); });
  await waitFor(() => expect(net.writes()).toHaveLength(2));
  await release(first, outcome === "success" ? json({ id: 1 }) : json({ detail: "A failed" }, 409));
  expect(actions.cancelRow?.id).toBe(2);
  expect(actions.editable()).toBe(false);
  expect(invalidate).not.toHaveBeenCalled();
  expect(screen.queryByText(/A cancelled|A failed|Stale/)).not.toBeInTheDocument();
  act(() => { void actions.runAction("/admin/requests/2/cancel", {}, "Duplicate", "Failed"); });
  expect(net.writes()).toHaveLength(2);
  await release(second, json({ id: 2 }));
  await screen.findByText("B cancelled");
  expect(actions.cancelRow).toBeNull();
});
