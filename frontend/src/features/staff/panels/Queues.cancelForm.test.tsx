import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it } from "vitest";
import {
  endHardwareTest, hardwareHttp, held, json, mountHardware, release, startHardwareTest,
} from "../../../test/hardwareOwnershipHarness";
import {
  cancelPanel, cancelReason, openCancel, submitCancel, writeCancelReason,
} from "../../../test/cancelRequestHarness";

beforeEach(startHardwareTest);
afterEach(endHardwareTest);

it.each([
  { reason: "", error: "Reason is required." },
  { reason: " \n\t ", error: "Reason is required." },
  { reason: "x".repeat(501), error: "Reason must be 500 characters or fewer." },
])("refuses invalid cancellation reason: $error ($reason.length characters)", async ({ reason, error }) => {
  const net = hardwareHttp();
  mountHardware(cancelPanel());
  await openCancel();
  expect(cancelReason()).toBeRequired();
  expect(cancelReason()).toHaveAttribute("maxlength", "500");
  expect(cancelReason()).toHaveAccessibleDescription("Required. Up to 500 characters. Visible to staff only.");
  writeCancelReason(reason);
  submitCancel();
  expect(cancelReason()).toHaveAttribute("aria-invalid", "true");
  expect(cancelReason()).toHaveAccessibleDescription(error);
  expect(screen.getByText(error)).toBeVisible();
  expect(net.writes()).toEqual([]);
});

it.each([
  { label: "one trimmed character", reason: " \n a \t " },
  { label: "500 characters", reason: "x".repeat(500) },
])("posts the trimmed reason to the selected request: $label", async ({ reason }) => {
  const net = hardwareHttp();
  mountHardware(cancelPanel());
  const modal = await openCancel("Borrower B");
  expect(screen.getByRole("alertdialog", { name: "Cancel request #2?" })).toHaveAccessibleDescription(/releases the reserved stock/);
  writeCancelReason(reason);
  fireEvent.click(modal.getByRole("button", { name: "Cancel request" }));
  await screen.findByText("Request #2 cancelled.");
  expect(net.writes()).toHaveLength(1);
  expect(net.writes()[0]).toMatchObject({ method: "POST", path: "/admin/requests/2/cancel", body: { reason: reason.trim() } });
  expect(net.writes()[0].init.body).toBe(JSON.stringify({ reason: reason.trim() }));
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
});

it("Go back sends no request and reopening starts an empty draft", async () => {
  const net = hardwareHttp();
  mountHardware(cancelPanel());
  const modal = await openCancel();
  writeCancelReason("Changed plans");
  fireEvent.click(modal.getByRole("button", { name: "Go back" }));
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  expect(net.writes()).toEqual([]);
  await openCancel();
  expect(cancelReason()).toHaveValue("");
});

it("409 retains the reason and server error; only an explicit retry sends again", async () => {
  let attempts = 0;
  const net = hardwareHttp((call) => call.path.endsWith("/cancel") && ++attempts === 1
    ? json({ detail: "Request has already been issued." }, 409) : undefined);
  mountHardware(cancelPanel());
  await openCancel();
  writeCancelReason("  Borrower changed plans  ");
  submitCancel();
  await screen.findAllByText("Request has already been issued.");
  await waitFor(() => expect(cancelReason()).toBeEnabled());
  expect(cancelReason()).toHaveValue("  Borrower changed plans  ");
  expect(net.writes()).toHaveLength(1);
  submitCancel();
  await screen.findByText("Request #1 cancelled.");
  expect(net.writes()).toHaveLength(2);
  expect(net.writes().map((call) => call.body)).toEqual([
    { reason: "Borrower changed plans" }, { reason: "Borrower changed plans" },
  ]);
});

it("pending freezes edits, buttons, Escape and backdrop close, including duplicate submits in one tick", async () => {
  const response = held<Response>();
  const net = hardwareHttp((call) => call.path.endsWith("/cancel") ? response.promise : undefined);
  mountHardware(cancelPanel());
  const modal = await openCancel();
  writeCancelReason("Original reason");
  act(() => { submitCancel(); submitCancel(); });
  await waitFor(() => expect(net.writes()).toHaveLength(1));
  expect(cancelReason()).toBeDisabled();
  expect(modal.getByRole("button", { name: "Go back" })).toBeDisabled();
  expect(modal.getByRole("button", { name: "Cancelling…" })).toBeDisabled();
  expect(modal.queryByRole("button", { name: "Close dialog" })).not.toBeInTheDocument();
  writeCancelReason("Forced replacement");
  fireEvent.click(modal.getByRole("button", { name: "Go back" }));
  fireEvent.keyDown(document, { key: "Escape" });
  const overlay = screen.getByRole("alertdialog").parentElement!;
  fireEvent.mouseDown(overlay);
  submitCancel();
  expect(screen.getByRole("alertdialog")).toBeVisible();
  expect(net.writes()).toHaveLength(1);
  expect(net.writes()[0].body).toEqual({ reason: "Original reason" });
  await release(response, json({ detail: "Please retry cancellation." }, 409));
  await screen.findAllByText("Please retry cancellation.");
  await waitFor(() => expect(cancelReason()).toBeEnabled());
  expect(cancelReason()).toHaveValue("Original reason");
});
