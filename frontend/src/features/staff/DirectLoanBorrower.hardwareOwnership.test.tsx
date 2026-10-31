import { useState } from "react";
import { onlineManager, useQuery } from "@tanstack/react-query";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { DirectLoanBorrower } from "./DirectLoanBorrower";
import { staffRequest } from "../../lib/api";
import type { PaginatedAdminMembershipList } from "../../generated/api";
import {
  field, endHardwareTest, hardwareHttp, held, json, login, maker, members, mountHardware,
  page, paused, release, resume, setValue, startHardwareTest,
} from "../../test/hardwareOwnershipHarness";

beforeEach(startHardwareTest);
afterEach(endHardwareTest);
function Borrower({ subject = "11", canEdit = () => true }) {
  const [selected, setSelected] = useState(subject);
  return <DirectLoanBorrower makerspaceId={maker.id} members={members} loading={false} error={null}
    borrowerId={selected} onBorrowerChange={setSelected} membershipOn canEdit={canEdit} />;
}
const witness = () => screen.getByRole("button", { name: "Record witnessed waiver acceptance" });
function MemberRosterObserver() {
  const roster = useQuery({ queryKey: ["members", 7, "roster"],
    queryFn: () => staffRequest<PaginatedAdminMembershipList>("/admin/memberships?makerspace_id=7") });
  return <p>{roster.data ? "Roster loaded" : "Loading roster"}</p>;
}

it("current waiver captures membership A, blocks duplicates/borrower edits, and invalidates its member data", async () => {
  const response = held<Response>();
  let rosterReads = 0;
  const net = hardwareHttp((call) => call.path === "/admin/memberships?makerspace_id=7"
    ? (++rosterReads, json(page([]))) : call.path.endsWith("/waiver/witness") ? response.promise : undefined);
  const view = mountHardware(<><Borrower /><MemberRosterObserver /></>);
  await screen.findByText("Roster loaded");
  const invalidate = vi.spyOn(view.client, "invalidateQueries");
  const button = witness();
  act(() => { fireEvent.click(button); setValue("Borrowing member", "12"); fireEvent.click(button); });
  await waitFor(() => expect(net.writes()).toHaveLength(1));
  expect(field("Borrowing member")).toHaveValue("11");
  expect(net.writes()[0]).toMatchObject({ path: "/admin/memberships/101/waiver/witness", body: {} });
  await release(response, json({ id: 101 }));
  await screen.findAllByText("Waiver acceptance recorded.");
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["members", 7] });
  await waitFor(() => expect(rosterReads).toBe(2));
  await waitFor(() => expect(field("Borrowing member")).toBeEnabled());
  setValue("Borrowing member", "12");
  // A's toast can persist; B must not acquire the inline success indicator.
  expect(screen.getAllByText("Waiver acceptance recorded.")).toHaveLength(1);
});

it.each(["subject", "actor"])("paused waiver never dispatches as B after %s change", async (change) => {
  const net = hardwareHttp();
  const props = { makerspaceId: 7, members, loading: false, error: null, onBorrowerChange: vi.fn(), membershipOn: true };
  const view = mountHardware(<DirectLoanBorrower {...props} borrowerId="11" />);
  onlineManager.setOnline(false);
  fireEvent.click(witness());
  await paused(view.client);
  if (change === "actor") login("B");
  view.rerender(<DirectLoanBorrower {...props} borrowerId="12" />);
  await waitFor(() => expect(field("Borrowing member")).toHaveValue("12"));
  await resume(view.client);
  expect(net.writes()).toHaveLength(0);
  expect(screen.queryByText(/Waiver acceptance recorded\.|Borrower selection changed/)).not.toBeInTheDocument();
  fireEvent.click(witness());
  await waitFor(() => expect(net.writes()).toHaveLength(1));
  expect(net.writes()[0].path).toBe("/admin/memberships/102/waiver/witness");
});

it("same mounted borrower subject change invalidates held A waiver completion", async () => {
  const response = held<Response>();
  const net = hardwareHttp((call) => call.path.endsWith("/waiver/witness") ? response.promise : undefined);
  const choose = vi.fn();
  const props = { makerspaceId: 7, members, loading: false, error: null, onBorrowerChange: choose, membershipOn: true };
  const view = mountHardware(<DirectLoanBorrower {...props} borrowerId="11" />);
  fireEvent.click(witness());
  await waitFor(() => expect(net.writes()).toHaveLength(1));
  view.rerender(<DirectLoanBorrower {...props} borrowerId="12" />);
  await waitFor(() => expect(field("Borrowing member")).toHaveValue("12"));
  await release(response, json({ id: 101 }));
  expect(screen.queryByText("Waiver acceptance recorded.")).not.toBeInTheDocument();
  expect(field("Borrowing member")).toBeEnabled();
});

it("synchronous handout admission blocks dropdown, walk-in creation and witness paths before disabled paint", async () => {
  const net = hardwareHttp(); let editable = true;
  const view = mountHardware(<Borrower canEdit={() => editable} />);
  fireEvent.click(screen.getByRole("button", { name: "Not in the list? Add a walk-in" }));
  setValue("Name", "Desk person");
  editable = false; // Same parent owner predicate that issue admission closes synchronously.
  act(() => {
    setValue("Borrowing member", "12");
    fireEvent.click(witness());
    fireEvent.click(screen.getByRole("button", { name: "Add walk-in" }));
  });
  expect(net.writes()).toHaveLength(0);
  expect(field("Borrowing member")).toHaveValue("11");
  editable = true;
  view.rerender(<Borrower canEdit={() => editable} />);
  setValue("Borrowing member", "12");
  expect(field("Borrowing member")).toHaveValue("12");
});
