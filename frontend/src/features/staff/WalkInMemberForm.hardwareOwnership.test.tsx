import { onlineManager } from "@tanstack/react-query";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { WalkInMemberForm } from "./WalkInMemberForm";
import { DirectLoans } from "./DirectLoans";
import { CanonicalRoster, observedPeople } from "../../test/walkInRosterHarness";
import {
  field, endHardwareTest, hardwareHttp, held, json, login, maker, members, mountHardware,
  page, paused, release, resume, setValue, startHardwareTest, uploadPhoto, waitForChoice,
} from "../../test/hardwareOwnershipHarness";

beforeEach(startHardwareTest);
afterEach(endHardwareTest);
const created = { user_id: 13, display_name: "Desk person", username: "walk-in-13" };
const roster = [...members, { ...created, membership_id: 103, is_walk_in: true }];
function fill() {
  fireEvent.click(screen.getByRole("button", { name: "Not in the list? Add a walk-in" }));
  setValue("Name", " Desk person ");
  setValue("Email", " desk@example.test ");
  setValue("Phone", " +911234567890 ");
}

it("paused creation snapshots identity and prevents same-tick edits/duplicates; current creation selects once", async () => {
  const selected = vi.fn();
  let committed = false;
  const net = hardwareHttp((call) => {
    if (call.path.endsWith("/walk-in-members")) { committed = true; return json(created); }
    if (call.path.includes("/direct-loan-members")) return json(page(committed ? roster : members));
  });
  const view = mountHardware(<CanonicalRoster><WalkInMemberForm makerspaceId={7} onCreated={selected} /></CanonicalRoster>);
  await observedPeople();
  fill();
  onlineManager.setOnline(false);
  const button = screen.getByRole("button", { name: "Add walk-in" });
  act(() => {
    fireEvent.click(button);
    setValue("Name", "Later person"); setValue("Email", "later@example.test"); setValue("Phone", "000");
    fireEvent.click(button);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  });
  await paused(view.client);
  expect(net.writes()).toHaveLength(0);
  expect(field("Name")).toHaveValue(" Desk person ");
  await resume(view.client);
  await waitFor(() => expect(selected).toHaveBeenCalledExactlyOnceWith(13));
  expect(net.writes()).toHaveLength(1);
  expect(net.writes()[0]).toMatchObject({ path: "/admin/makerspaces/7/walk-in-members", body: {
    display_name: "Desk person", email: "desk@example.test", phone: "+911234567890",
  } });
});

it.each(["actor", "visit"])("paused creation loses dispatch authority after %s departure", async (departure) => {
  const selected = vi.fn();
  const net = hardwareHttp();
  const view = mountHardware(<WalkInMemberForm key="A" makerspaceId={7} onCreated={selected} />);
  fill();
  onlineManager.setOnline(false);
  fireEvent.click(screen.getByRole("button", { name: "Add walk-in" }));
  await paused(view.client);
  if (departure === "actor") login("B");
  view.rerender(<WalkInMemberForm key="B" makerspaceId={7} onCreated={selected} />);
  fill();
  setValue("Name", "B form");
  await resume(view.client);
  expect(net.writes()).toHaveLength(0);
  expect(selected).not.toHaveBeenCalled();
  expect(field("Name")).toHaveValue("B form");
  expect(screen.queryByText(/Walk-in form changed|added$/)).not.toBeInTheDocument();
});

it.each(["current", "new-borrower", "new-visit", "issue-pending"])("committed creation waits for held roster; %s owns any eventual selection", async (next) => {
  const refreshed = held<Response>(); let committed = false; let rosterReads = 0;
  const net = hardwareHttp((call) => {
    if (call.path.endsWith("/walk-in-members")) { committed = true; return json(created); }
    if (call.method === "GET" && call.path.includes("/direct-loan-members")) {
      rosterReads += 1;
      return committed ? refreshed.promise : json(page(members));
    }
  });
  const view = mountHardware(<DirectLoans key="A" makerspace={maker} />);
  await waitForChoice("Borrowing member", "11");
  setValue("Borrowing member", "11");
  fill();
  fireEvent.click(screen.getByRole("button", { name: "Add walk-in" }));
  await waitFor(() => expect(rosterReads).toBe(2));
  expect(field("Borrowing member")).toHaveValue("11");
  expect(field("Borrowing member").querySelector('option[value="13"]')).not.toBeInTheDocument();
  if (next === "new-borrower") setValue("Borrowing member", "12");
  if (next === "new-visit") {
    view.rerender(<DirectLoans key="B" makerspace={maker} />);
    await waitFor(() => expect(field("Borrowing member")).toHaveValue(""));
    setValue("Borrowing member", "12");
  }
  if (next === "issue-pending") {
    setValue("Product", "5");
    // Use the real evidence upload and real issue admission, rather than a fake pending prop.
    await uploadPhoto();
    onlineManager.setOnline(false);
    fireEvent.click(screen.getByRole("button", { name: "Issue direct handout" }));
    await paused(view.client);
  }
  await release(refreshed, json(page(roster)));
  await waitForChoice("Borrowing member", "13");
  await waitFor(() => expect(view.client.isMutating({ predicate: (m) =>
    typeof m.state.variables === "object" && m.state.variables !== null && "path" in m.state.variables &&
    String(m.state.variables.path).endsWith("/walk-in-members"),
  })).toBe(0));
  expect(field("Borrowing member")).toHaveValue(next === "current" ? "13" : next === "issue-pending" ? "11" : "12");
  expect(net.calls.filter((call) => call.path.endsWith("/walk-in-members"))).toHaveLength(1);
  if (next === "issue-pending") {
    await resume(view.client);
    await screen.findByText("Handout issued.");
    expect(net.calls.find((call) => call.method === "POST" && call.path.endsWith("/direct-loans"))?.body.borrower_id).toBe(11);
  }
});

it("current creation error releases only its own pending state and retry keeps identity details", async () => {
  const selected = vi.fn(); let fail = true; let committed = false;
  const net = hardwareHttp((call) => {
    if (call.path.endsWith("/walk-in-members")) {
      if (fail) return json({ detail: "Walk-in creation busy" }, 409);
      committed = true; return json(created);
    }
    if (call.path.includes("/direct-loan-members")) return json(page(committed ? roster : members));
  });
  mountHardware(<CanonicalRoster><WalkInMemberForm makerspaceId={7} onCreated={selected} /></CanonicalRoster>);
  fill();
  fireEvent.click(screen.getByRole("button", { name: "Add walk-in" }));
  await screen.findAllByText("Walk-in creation busy");
  await waitFor(() => expect(field("Name")).toBeEnabled());
  expect(field("Name")).toHaveValue(" Desk person ");
  fail = false;
  fireEvent.click(screen.getByRole("button", { name: "Add walk-in" }));
  await waitFor(() => expect(selected).toHaveBeenCalledExactlyOnceWith(13));
  expect(net.writes()).toHaveLength(2);
  expect(net.writes()[1].body).toEqual(net.writes()[0].body);
});
