import { act, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { WalkInMemberForm } from "./WalkInMemberForm";
import { staffRequest } from "../../lib/api";
import {
  endHardwareTest, field, held, json, members, mountHardware, page, release, startHardwareTest,
} from "../../test/hardwareOwnershipHarness";
import {
  addWalkIn, canonicalPeople, CanonicalRoster, fillWalkIn, forceClicks, observedPeople,
  personReceipt, refreshBorrowers, rosterHttp, rosterKey, rosterPath, selectionNeedsRefresh, submittedPerson,
} from "../../test/walkInRosterHarness";

beforeEach(startHardwareTest);
afterEach(endHardwareTest);

it("a committed POST followed by real 503 keeps a receipt and retries only the canonical GET", async () => {
  const selected = vi.fn(); let committed = false; let fail = true;
  const refreshed = held<Response>();
  const net = rosterHttp((call) => {
    if (call.method === "POST") { committed = true; return json(personReceipt); }
    if (call.path === rosterPath) return !committed ? json(page(members))
      : fail ? json({ detail: "Roster unavailable" }, 503) : refreshed.promise;
  });
  const view = mountHardware(<CanonicalRoster><WalkInMemberForm makerspaceId={7} onCreated={selected} /></CanonicalRoster>);
  const invalidate = vi.spyOn(view.client, "invalidateQueries"); // Call through to the real client.
  await observedPeople();
  fillWalkIn();
  const add = screen.getByRole("button", { name: "Add walk-in" });
  forceClicks(add);
  await selectionNeedsRefresh();
  expect(invalidate).toHaveBeenCalledWith({ queryKey: rosterKey, exact: true, refetchType: "none" }, { throwOnError: true });
  expect(view.client.getQueryState(rosterKey)).toMatchObject({ status: "error", fetchStatus: "idle" });
  expect(net.responses.map((row) => [row.call.method, row.status])).toEqual([["GET", 200], ["POST", 200], ["GET", 503]]);
  expect(net.responses[1].body).toEqual(personReceipt);
  expect(Object.keys(personReceipt).sort()).toEqual(["display_name", "user_id", "username"]);
  expect(view.client.getQueryData(rosterKey)).toEqual(page(members));
  expect(selected).not.toHaveBeenCalled();
  fail = false;
  const retry = screen.getByRole("button", { name: "Refresh borrower list" });
  forceClicks(retry);
  await waitFor(() => expect(net.reads()).toHaveLength(3));
  expect(selected).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  expect(net.writes()).toHaveLength(1);
  expect(net.writes()[0].body).toEqual(submittedPerson);
  await release(refreshed, json(page(canonicalPeople)));
  await observedPeople(canonicalPeople);
  await waitFor(() => expect(selected).toHaveBeenCalledExactlyOnceWith(13));
  expect(view.client.getQueryData(rosterKey)).toEqual(net.responses[net.responses.length - 1]?.body);
  expect(net.calls.map((call) => call.method)).toEqual(["GET", "POST", "GET", "GET"]);
  expect(net.responses[net.responses.length - 1]).toMatchObject({ status: 200, body: page(canonicalPeople) });
});

it("a successful capped roster without the created ID stays truthful across read-only retries", async () => {
  const selected = vi.fn(); let committed = false;
  const capped = { count: 1001, next: "/next-page", previous: null, results: members };
  const net = rosterHttp((call) => {
    if (call.method === "POST") { committed = true; return json(personReceipt); }
    if (call.path === rosterPath) return json(committed ? capped : page(members));
  });
  const view = mountHardware(<CanonicalRoster><WalkInMemberForm makerspaceId={7} onCreated={selected} /></CanonicalRoster>);
  await observedPeople(); fillWalkIn(); addWalkIn();
  await selectionNeedsRefresh();
  refreshBorrowers();
  await waitFor(() => expect(net.reads()).toHaveLength(3));
  await selectionNeedsRefresh();
  expect(view.client.getQueryData(rosterKey)).toEqual(capped);
  expect(screen.getByTestId("canonical-roster").textContent).toBe(JSON.stringify(capped));
  expect(selected).not.toHaveBeenCalled();
  expect(net.writes()).toHaveLength(1);
  expect(net.responses.filter((r) => r.call.method === "GET").every((r) => r.status === 200)).toBe(true);
});

it("cached canonical ID cannot authorize selection when the actual read fails", async () => {
  const selected = vi.fn(); let committed = false;
  const net = rosterHttp((call) => {
    if (call.method === "POST") { committed = true; return json(personReceipt); }
    if (call.path === rosterPath) return committed ? json({ detail: "Read failed" }, 503) : json(page(canonicalPeople));
  });
  const view = mountHardware(<CanonicalRoster><WalkInMemberForm makerspaceId={7} onCreated={selected} /></CanonicalRoster>);
  await observedPeople(canonicalPeople); fillWalkIn(); addWalkIn();
  await selectionNeedsRefresh();
  expect(view.client.getQueryData(rosterKey)).toEqual(page(canonicalPeople));
  expect(view.client.getQueryState(rosterKey)?.status).toBe("error");
  expect(selected).not.toHaveBeenCalled();
  expect(net.responses[net.responses.length - 1]?.status).toBe(503);
});

it.each(["missing", "inactive", "disabled", "static"] as const)("%s canonical query cannot turn cached success into selection", async (mode) => {
  const selected = vi.fn();
  const net = rosterHttp((call) => call.method === "POST" ? json(personReceipt)
    : call.path === rosterPath ? json(page(canonicalPeople)) : undefined);
  const form = <WalkInMemberForm makerspaceId={7} onCreated={selected} />;
  const view = mountHardware(mode === "missing" ? form : <><CanonicalRoster />{form}</>);
  if (mode !== "missing") {
    await observedPeople(canonicalPeople);
    view.rerender(<>{mode === "inactive" ? null
      : <CanonicalRoster enabled={mode !== "disabled"} staleTime={mode === "static" ? "static" : 30_000} />}{form}</>);
  }
  const reads = net.reads().length;
  fillWalkIn(); addWalkIn();
  await selectionNeedsRefresh();
  refreshBorrowers(); await selectionNeedsRefresh();
  expect(net.reads()).toHaveLength(reads);
  expect(selected).not.toHaveBeenCalled();
  expect(net.writes()).toHaveLength(1);
  expect(view.client.getQueryData(rosterKey)).toEqual(mode === "missing" ? undefined : page(canonicalPeople));
});

it.each(["remove", "replace"] as const)("%s while waiting retires the exact query, even if a new query has a real cached success", async (mode) => {
  const selected = vi.fn(); const pending = held<Response>(); let committed = false; let replacement = false;
  const net = rosterHttp((call) => {
    if (call.method === "POST") { committed = true; return json(personReceipt); }
    if (call.path === rosterPath) return replacement ? json(page(canonicalPeople))
      : committed ? pending.promise : json(page(members));
  });
  const view = mountHardware(<CanonicalRoster><WalkInMemberForm makerspaceId={7} onCreated={selected} /></CanonicalRoster>);
  await observedPeople(); fillWalkIn(); addWalkIn();
  await waitFor(() => expect(net.reads()).toHaveLength(2));
  const original = view.client.getQueryCache().find({ queryKey: rosterKey, exact: true });
  act(() => view.client.removeQueries({ queryKey: rosterKey, exact: true }));
  if (mode === "replace") {
    replacement = true;
    await act(async () => { await view.client.fetchQuery({ queryKey: rosterKey,
      queryFn: () => staffRequest(rosterPath), gcTime: Infinity }); });
    expect(view.client.getQueryCache().find({ queryKey: rosterKey, exact: true })).not.toBe(original);
    expect(view.client.getQueryData(rosterKey)).toEqual(page(canonicalPeople));
  }
  await selectionNeedsRefresh();
  await release(pending, json(page(canonicalPeople)));
  expect(selected).not.toHaveBeenCalled();
  expect(screen.queryByText("Desk person added")).not.toBeInTheDocument();
  expect(net.writes()).toHaveLength(1);
});

it("failed POST retains all inputs for genuine retry, then receipt retries never create again", async () => {
  const selected = vi.fn(); let posts = 0;
  const net = rosterHttp((call) => {
    if (call.method === "POST") return ++posts === 1 ? json({ detail: "Creation refused" }, 409) : json(personReceipt);
    if (call.path === rosterPath) return posts < 2 ? json(page(members)) : json({ detail: "Roster down" }, 503);
  });
  mountHardware(<CanonicalRoster><WalkInMemberForm makerspaceId={7} onCreated={selected} /></CanonicalRoster>);
  await observedPeople(); fillWalkIn(); addWalkIn();
  await screen.findAllByText("Creation refused");
  await waitFor(() => expect(field("Name")).toBeEnabled());
  expect(field("Name")).toHaveValue(" Desk person ");
  // Native email inputs normalize surrounding whitespace before React receives the value.
  expect(field("Email")).toHaveValue("desk@example.test");
  expect(field("Phone")).toHaveValue(" +911234567890 ");
  forceClicks(screen.getByRole("button", { name: "Add walk-in" }));
  await selectionNeedsRefresh(); refreshBorrowers();
  await waitFor(() => expect(net.reads()).toHaveLength(3));
  await selectionNeedsRefresh();
  expect(net.writes().map((call) => call.body)).toEqual([submittedPerson, submittedPerson]);
  expect(selected).not.toHaveBeenCalled();
});
