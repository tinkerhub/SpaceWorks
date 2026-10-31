import type { ComponentProps } from "react";
import { fireEvent, screen, within } from "@testing-library/react";
import { Queues } from "../features/staff/panels/Queues";
import { maker, queueAction } from "./hardwareOwnershipHarness";

// Keep the real Queues → modal → ownership → transport path in every form test.
export function cancelPanel(props: Partial<ComponentProps<typeof Queues>> = {}) {
  return <Queues makerspace={maker} guestOnly={false} canReturnRequest={false}
    canReviewRequests={false} canCancelRequests {...props} />;
}
export async function openCancel(person = "Borrower A") {
  await screen.findByText(person);
  queueAction(person, "Cancel request…");
  return within(screen.getByRole("alertdialog"));
}
export function cancelReason() { return screen.getByRole("textbox", { name: "Reason" }); }
export function writeCancelReason(value: string) {
  fireEvent.change(cancelReason(), { target: { value } });
}
export function submitCancel() {
  const form = cancelReason().closest("form");
  if (!form) throw new Error("Missing cancellation form");
  // Submit directly so validation is exercised even for forced invalid DOM events.
  fireEvent.submit(form);
}
