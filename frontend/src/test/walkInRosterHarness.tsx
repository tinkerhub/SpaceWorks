import { useQuery } from "@tanstack/react-query";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { expect } from "vitest";
import { staffRequest } from "../lib/api";
import type { DirectLoanMemberResponse } from "../features/staff/DirectLoanTypes";
import { hardwareHttp, members, page, setValue } from "./hardwareOwnershipHarness";
import type { HttpCall } from "./staffUploadHarness";

export const rosterKey = ["direct-loan-members", 7];
export const rosterPath = "/admin/makerspace/7/direct-loan-members?page_size=1000";
// Independent server DTOs: the POST receipt has no membership or waiver information.
export const personReceipt = { user_id: 13, display_name: "Desk person", username: "walk-in-13" };
export const canonicalPeople = [...members, {
  membership_id: 103, user_id: 13, display_name: "Desk person", username: "walk-in-13", is_walk_in: true,
}];
export const submittedPerson = { display_name: "Desk person", email: "desk@example.test", phone: "+911234567890" };

/** Real observer and canonical HTTP query; no admission or ownership decisions in this fixture. */
export function CanonicalRoster({ children, enabled = true, retry = false, staleTime = 30_000 }: {
  children?: ReactNode; enabled?: boolean; retry?: number | boolean; staleTime?: number | "static";
}) {
  const roster = useQuery({
    queryKey: rosterKey, queryFn: () => staffRequest<DirectLoanMemberResponse>(rosterPath),
    enabled, retry, staleTime, gcTime: Infinity,
  });
  return <>
    <output data-testid="canonical-roster" data-fetch={roster.fetchStatus} data-status={roster.status}>
      {JSON.stringify(roster.data ?? null)}
    </output>
    {children}
  </>;
}

/** Preserve the actual HTTP order, response status/body and POST payloads for assertions. */
export function rosterHttp(respond: (call: HttpCall) => Response | Promise<Response> | undefined) {
  const responses: { call: HttpCall; status: number; body: unknown }[] = [];
  const net = hardwareHttp((call) => {
    const response = respond(call);
    if (response === undefined) return undefined;
    return Promise.resolve(response).then(async (value) => {
      responses.push({ call, status: value.status, body: await value.clone().json() });
      return value.clone(); // A held server reply may serve observers which joined the same read.
    });
  });
  return { ...net, responses, reads: () => net.calls.filter((call) => call.path === rosterPath) };
}

export function fillWalkIn(name = " Desk person ") {
  fireEvent.click(screen.getByRole("button", { name: "Not in the list? Add a walk-in" }));
  setValue("Name", name);
  setValue("Email", " desk@example.test ");
  setValue("Phone", " +911234567890 ");
}
export function addWalkIn() { fireEvent.click(screen.getByRole("button", { name: "Add walk-in" })); }
export function refreshBorrowers() { fireEvent.click(screen.getByRole("button", { name: "Refresh borrower list" })); }
export async function selectionNeedsRefresh() {
  await screen.findByText("Desk person was added. Refresh the borrower list to select them.");
  await waitFor(() => expect(screen.getByRole("button", { name: "Refresh borrower list" })).toBeEnabled());
  expect(screen.queryByText(/Couldn't add the walk-in|Walk-in form changed/)).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Add walk-in" })).not.toBeInTheDocument();
}
export async function observedPeople(people = members) {
  await waitFor(() => expect(screen.getByTestId("canonical-roster").textContent).toBe(JSON.stringify(page(people))));
}
/** Dispatch even to a disabled retained button to exercise the synchronous guard. */
export function forceClicks(button: HTMLElement) {
  act(() => {
    button.removeAttribute("disabled");
    fireEvent.click(button);
    button.removeAttribute("disabled");
    fireEvent.click(button);
  });
}
