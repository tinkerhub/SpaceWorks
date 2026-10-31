import { onlineManager } from "@tanstack/react-query";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { WalkInMemberForm } from "./WalkInMemberForm";
import { DirectLoans } from "./DirectLoans";
import {
  endHardwareTest, field, held, json, login, maker, members, mountHardware, page,
  release, setValue, startHardwareTest, uploadPhoto, waitForChoice,
} from "../../test/hardwareOwnershipHarness";
import {
  addWalkIn, canonicalPeople, CanonicalRoster, fillWalkIn, observedPeople, personReceipt,
  refreshBorrowers, rosterHttp, rosterKey, rosterPath, selectionNeedsRefresh,
} from "../../test/walkInRosterHarness";

beforeEach(startHardwareTest);
afterEach(endHardwareTest);

it.each(["failed", "paused"] as const)("cancel/reopen after %s selection clears committed contacts and cannot offer a disguised POST retry", async (selection) => {
  const selected = vi.fn(); let committed = false;
  const net = rosterHttp((call) => {
    if (call.method === "POST") {
      committed = true;
      if (selection === "paused") onlineManager.setOnline(false);
      return json(personReceipt);
    }
    if (call.path === rosterPath) return committed ? json({ detail: "Roster down" }, 503) : json(page(members));
  });
  mountHardware(<CanonicalRoster><WalkInMemberForm makerspaceId={7} onCreated={selected} /></CanonicalRoster>);
  await observedPeople(); fillWalkIn(); addWalkIn(); await selectionNeedsRefresh();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  fireEvent.click(screen.getByRole("button", { name: "Not in the list? Add a walk-in" }));
  for (const label of ["Name", "Email", "Phone"]) expect(field(label)).toHaveValue("");
  const add = screen.getByRole("button", { name: "Add walk-in" });
  expect(add).toBeDisabled();
  fireEvent.click(add);
  expect(net.writes()).toHaveLength(1);
  expect(selected).not.toHaveBeenCalled();
});

it.each(["actor", "captured-parent", "latest-parent", "navigation", "unmount"] as const)("held receipt refresh released after %s departure cannot publish or revive", async (departure) => {
  const selected = vi.fn(); const waiting = held<Response>(); let committed = false; let retry = false;
  let capturedAllowed = true;
  const capturedEdit = () => capturedAllowed;
  const net = rosterHttp((call) => {
    if (call.method === "POST") { committed = true; return json(personReceipt); }
    if (call.path === rosterPath) return !committed ? json(page(members))
      : retry ? waiting.promise : json({ detail: "Roster down" }, 503);
  });
  const renderForm = (canEdit = capturedEdit) => <CanonicalRoster>
    <WalkInMemberForm makerspaceId={7} onCreated={selected} canEdit={canEdit} />
  </CanonicalRoster>;
  const view = mountHardware(renderForm());
  await observedPeople(); fillWalkIn(); addWalkIn(); await selectionNeedsRefresh();
  retry = true; refreshBorrowers();
  await waitFor(() => expect(net.reads()).toHaveLength(3));
  if (departure === "actor") { act(() => login("B")); view.rerender(renderForm()); }
  if (departure === "captured-parent") { capturedAllowed = false; view.rerender(renderForm(() => true)); }
  if (departure === "latest-parent") view.rerender(renderForm(() => false));
  if (departure === "navigation") view.rerender(<p>Another staff page</p>);
  if (departure === "unmount") view.unmount();
  if (["captured-parent", "latest-parent", "actor"].includes(departure)) {
    // Returning to editable does not resurrect the old receipt or submitted fields.
    capturedAllowed = true; view.rerender(renderForm());
    expect(field("Name")).toHaveValue("");
    setValue("Name", "B untouched draft");
  }
  await release(waiting, json(page(canonicalPeople)));
  await waitFor(() => expect(view.client.isFetching({ queryKey: rosterKey })).toBe(0));
  expect(selected).not.toHaveBeenCalled();
  expect(screen.queryByText("Desk person added")).not.toBeInTheDocument();
  expect(net.writes()).toHaveLength(1);
  if (["captured-parent", "latest-parent", "actor"].includes(departure)) {
    expect(field("Name")).toHaveValue("B untouched draft");
    expect(screen.queryByRole("button", { name: "Refresh borrower list" })).not.toBeInTheDocument();
  }
});

it("A's retired refresh cannot clear or unlock B's pending POST; only B's canonical record selects", async () => {
  const selectedA = vi.fn(); const selectedB = vi.fn();
  const oldRead = held<Response>(); const bPost = held<Response>(); let posts = 0; let retry = false;
  const bReceipt = { user_id: 14, display_name: "B person", username: "walk-in-14" };
  const bPeople = [...canonicalPeople, {
    membership_id: 104, user_id: 14, display_name: "B person", username: "walk-in-14", is_walk_in: true,
  }];
  const net = rosterHttp((call) => {
    if (call.method === "POST") return ++posts === 1 ? json(personReceipt) : bPost.promise;
    if (call.path === rosterPath) return posts === 0 ? json(page(members)) : posts === 2
      ? json(page(bPeople)) : retry ? oldRead.promise : json({ detail: "Roster down" }, 503);
  });
  const view = mountHardware(<CanonicalRoster><WalkInMemberForm key="A" makerspaceId={7} onCreated={selectedA} /></CanonicalRoster>);
  await observedPeople(); fillWalkIn(); addWalkIn(); await selectionNeedsRefresh();
  retry = true; refreshBorrowers();
  await waitFor(() => expect(net.reads()).toHaveLength(3));
  view.rerender(<CanonicalRoster><WalkInMemberForm key="B" makerspaceId={7} onCreated={selectedB} /></CanonicalRoster>);
  fillWalkIn("B person"); addWalkIn();
  await waitFor(() => expect(net.writes()).toHaveLength(2));
  await release(oldRead, json(page(canonicalPeople)));
  await observedPeople(canonicalPeople);
  expect(selectedA).not.toHaveBeenCalled(); expect(selectedB).not.toHaveBeenCalled();
  expect(field("Name")).toHaveValue("B person");
  expect(field("Name")).toBeDisabled();
  expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  expect(screen.queryByText("Desk person added")).not.toBeInTheDocument();
  await release(bPost, json(bReceipt));
  await observedPeople(bPeople);
  await waitFor(() => expect(selectedB).toHaveBeenCalledExactlyOnceWith(14));
  expect(selectedA).not.toHaveBeenCalled();
  expect(net.writes()).toHaveLength(2);
});

it.each(["borrower-choice", "handout-intent", "navigation"] as const)("actual handout %s retires a held selection retry without undoing creation", async (departure) => {
  const waiting = held<Response>(); const issue = held<Response>(); let committed = false; let retry = false;
  const net = rosterHttp((call) => {
    if (call.path.endsWith("/walk-in-members")) { committed = true; return json(personReceipt); }
    if (call.method === "POST" && call.path.endsWith("/direct-loans")) return issue.promise;
    if (call.path === rosterPath) return !committed ? json(page(members))
      : retry ? waiting.promise : json({ detail: "Roster down" }, 503);
  });
  const view = mountHardware(<DirectLoans makerspace={maker} />);
  await waitForChoice("Borrowing member", "11");
  await waitForChoice("Product", "5");
  setValue("Borrowing member", "11"); setValue("Product", "5");
  await uploadPhoto();
  fillWalkIn(); addWalkIn(); await selectionNeedsRefresh();
  retry = true; refreshBorrowers();
  await waitFor(() => expect(net.reads()).toHaveLength(3));
  if (departure === "borrower-choice") setValue("Borrowing member", "12");
  if (departure === "navigation") view.rerender(<p>Another staff page</p>);
  if (departure === "handout-intent") {
    fireEvent.click(screen.getByRole("button", { name: "Issue direct handout" }));
    await waitFor(() => expect(net.calls.some((call) => call.method === "POST" && call.path.endsWith("/direct-loans"))).toBe(true));
    for (const label of ["Name", "Email", "Phone"]) expect(field(label)).toHaveValue("");
  }
  await release(waiting, json(page(canonicalPeople)));
  await waitFor(() => expect(view.client.isFetching({ queryKey: rosterKey })).toBe(0));
  expect(screen.queryByText("Desk person added")).not.toBeInTheDocument();
  expect(net.calls.filter((call) => call.path.endsWith("/walk-in-members"))).toHaveLength(1);
  if (departure === "borrower-choice") {
    await waitForChoice("Borrowing member", "13");
    expect(field("Borrowing member")).toHaveValue("12");
    fireEvent.click(screen.getByRole("button", { name: "Not in the list? Add a walk-in" }));
    for (const label of ["Name", "Email", "Phone"]) expect(field(label)).toHaveValue("");
  }
  if (departure === "handout-intent") {
    expect(field("Borrowing member")).toHaveValue("11");
    expect(field("Product")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    await release(issue, json({ id: 81 }));
    await screen.findByText("Handout issued.");
    fireEvent.click(screen.getByRole("button", { name: "Not in the list? Add a walk-in" }));
    for (const label of ["Name", "Email", "Phone"]) expect(field(label)).toHaveValue("");
    expect(net.calls.find((call) => call.method === "POST" && call.path.endsWith("/direct-loans"))?.body.borrower_id).toBe(11);
  }
});

it.each(["actor", "parent-intent", "navigation"] as const)("already dispatched POST commits after %s departure without publishing its old receipt", async (departure) => {
  const selected = vi.fn(); const post = held<Response>();
  const net = rosterHttp((call) => call.method === "POST" ? post.promise
    : call.path === rosterPath ? json(page(members)) : undefined);
  let editable = true;
  const form = () => <CanonicalRoster><WalkInMemberForm makerspaceId={7} onCreated={selected} canEdit={() => editable} /></CanonicalRoster>;
  const view = mountHardware(form());
  await observedPeople(); fillWalkIn(); addWalkIn();
  await waitFor(() => expect(net.writes()).toHaveLength(1));
  if (departure === "actor") { act(() => login("B")); view.rerender(form()); }
  if (departure === "parent-intent") { editable = false; view.rerender(form()); }
  if (departure === "navigation") view.rerender(<p>Another staff page</p>);
  await release(post, json(personReceipt)); // Server success is durable even though its UI owner left.
  await waitFor(() => expect(view.client.isMutating()).toBe(0));
  expect(net.responses.filter((r) => r.call.method === "POST")).toMatchObject([{ status: 200, body: personReceipt }]);
  expect(net.writes()).toHaveLength(1);
  expect(net.reads()).toHaveLength(1);
  expect(selected).not.toHaveBeenCalled();
  expect(screen.queryByText("Desk person added")).not.toBeInTheDocument();
  expect(screen.queryByText(/was added\./)).not.toBeInTheDocument();
});
