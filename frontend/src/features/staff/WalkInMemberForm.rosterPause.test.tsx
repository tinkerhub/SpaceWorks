import { onlineManager } from "@tanstack/react-query";
import { act, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { WalkInMemberForm } from "./WalkInMemberForm";
import {
  endHardwareTest, held, json, mountHardware, page, release, startHardwareTest,
} from "../../test/hardwareOwnershipHarness";
import {
  addWalkIn, canonicalPeople, CanonicalRoster, fillWalkIn, forceClicks, observedPeople,
  personReceipt, refreshBorrowers, rosterHttp, rosterKey, rosterPath, selectionNeedsRefresh,
} from "../../test/walkInRosterHarness";

beforeEach(startHardwareTest);
afterEach(endHardwareTest);

it("initially paused real roster releases creation pending; old shared success is not selection proof", async () => {
  const selected = vi.fn(); const oldRead = held<Response>(); const freshRead = held<Response>();
  let committed = false; let fresh = false;
  const net = rosterHttp((call) => {
    if (call.method === "POST") {
      committed = true;
      onlineManager.setOnline(false); // POST has reached the server; only the ensuing read pauses.
      return json(personReceipt);
    }
    if (call.path === rosterPath) return !committed ? json(page(canonicalPeople)) : fresh ? freshRead.promise : oldRead.promise;
  });
  const view = mountHardware(<CanonicalRoster retry={1}><WalkInMemberForm makerspaceId={7} onCreated={selected} /></CanonicalRoster>);
  await observedPeople(canonicalPeople); fillWalkIn(); addWalkIn();
  await waitFor(() => expect(view.client.getQueryState(rosterKey)?.fetchStatus).toBe("paused"));
  await selectionNeedsRefresh();
  await waitFor(() => expect(view.client.isMutating()).toBe(0));
  expect(net.reads()).toHaveLength(1);
  expect(selected).not.toHaveBeenCalled(); // Cached ID exists, but no read completed.
  // A second explicit attempt while offline also retires instead of waiting indefinitely.
  refreshBorrowers(); await selectionNeedsRefresh();
  expect(net.writes()).toHaveLength(1);
  act(() => onlineManager.setOnline(true));
  await waitFor(() => expect(net.reads()).toHaveLength(2));
  await release(oldRead, json(page(canonicalPeople)));
  await waitFor(() => expect(view.client.getQueryState(rosterKey)).toMatchObject({ status: "success", fetchStatus: "idle", isInvalidated: false }));
  await observedPeople(canonicalPeople);
  await selectionNeedsRefresh();
  expect(selected).not.toHaveBeenCalled();
  fresh = true;
  forceClicks(screen.getByRole("button", { name: "Refresh borrower list" }));
  await waitFor(() => expect(net.reads()).toHaveLength(3));
  expect(selected).not.toHaveBeenCalled();
  await release(freshRead, json(page(canonicalPeople)));
  await waitFor(() => expect(selected).toHaveBeenCalledExactlyOnceWith(13));
  expect(net.calls.map((call) => call.method)).toEqual(["GET", "POST", "GET", "GET"]);
});

it.each(["success", "rejection"] as const)("pause after failed fetch uses production retry:1; retired shared %s cannot publish", async (completion) => {
  const selected = vi.fn();
  const firstFailure = held<Response>(); const resumed = held<Response>(); const freshRead = held<Response>();
  let committed = false; let fresh = false; let postReads = 0;
  const net = rosterHttp((call) => {
    if (call.method === "POST") { committed = true; return json(personReceipt); }
    if (call.path === rosterPath) {
      if (!committed) return json(page(canonicalPeople));
      if (fresh) return freshRead.promise;
      return ++postReads === 1 ? firstFailure.promise : resumed.promise;
    }
  });
  const view = mountHardware(<CanonicalRoster retry={1}><WalkInMemberForm makerspaceId={7} onCreated={selected} /></CanonicalRoster>);
  await observedPeople(canonicalPeople); fillWalkIn(); addWalkIn();
  await waitFor(() => expect(net.reads()).toHaveLength(2));
  expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  act(() => onlineManager.setOnline(false));
  await release(firstFailure, json({ detail: "First roster read failed" }, 503));
  await waitFor(() => expect(view.client.getQueryState(rosterKey)?.fetchFailureCount).toBe(1));
  // Use TanStack's real retry delay and pause transition; no mocked invalidation/timers.
  await waitFor(() => expect(view.client.getQueryState(rosterKey)?.fetchStatus).toBe("paused"), { timeout: 3000 });
  expect(view.client.getQueryCache().find({ queryKey: rosterKey, exact: true })?.options.retry).toBe(1);
  await selectionNeedsRefresh();
  await waitFor(() => expect(view.client.isMutating()).toBe(0));
  expect(selected).not.toHaveBeenCalled();
  act(() => onlineManager.setOnline(true));
  await waitFor(() => expect(net.reads()).toHaveLength(3));
  await release(resumed, completion === "success" ? json(page(canonicalPeople)) : json({ detail: "Retry failed" }, 503));
  await waitFor(() => expect(view.client.getQueryState(rosterKey)).toMatchObject({
    status: completion === "success" ? "success" : "error", fetchStatus: "idle",
  }));
  await selectionNeedsRefresh();
  expect(selected).not.toHaveBeenCalled();
  expect(screen.queryByText("Desk person added")).not.toBeInTheDocument();
  expect(net.responses.filter((row) => row.call.path === rosterPath).map((row) => row.status))
    .toEqual([200, 503, completion === "success" ? 200 : 503]);
  fresh = true;
  refreshBorrowers();
  await waitFor(() => expect(net.reads()).toHaveLength(4));
  expect(selected).not.toHaveBeenCalled();
  await release(freshRead, json(page(canonicalPeople)));
  await observedPeople(canonicalPeople);
  await waitFor(() => expect(selected).toHaveBeenCalledExactlyOnceWith(13));
  expect(net.writes()).toHaveLength(1);
});
