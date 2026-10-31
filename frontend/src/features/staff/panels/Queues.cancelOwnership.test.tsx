import { onlineManager } from "@tanstack/react-query";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  endHardwareTest, hardwareHttp, held, json, login, maker, mountHardware,
  paused, release, resume, startHardwareTest,
} from "../../../test/hardwareOwnershipHarness";
import {
  cancelPanel, cancelReason, openCancel, submitCancel, writeCancelReason,
} from "../../../test/cancelRequestHarness";

beforeEach(startHardwareTest);
afterEach(endHardwareTest);

it("offline cancellation freezes the submitted reason until admission and sends only its original JSON", async () => {
  const net = hardwareHttp();
  const view = mountHardware(cancelPanel());
  await openCancel();
  writeCancelReason("  Original offline reason  ");
  onlineManager.setOnline(false);
  act(() => { submitCancel(); submitCancel(); });
  await paused(view.client);
  expect(net.writes()).toHaveLength(0);
  writeCancelReason("Forced later draft");
  submitCancel();
  await resume(view.client);
  await screen.findByText("Request #1 cancelled.");
  expect(net.writes()).toHaveLength(1);
  expect(net.writes()[0]).toMatchObject({ path: "/admin/requests/1/cancel", body: { reason: "Original offline reason" } });
  expect(net.writes()[0].init.body).toBe('{"reason":"Original offline reason"}');
});

it.each(["actor", "makerspace", "permission", "guest", "unmount"])(
  "queued cancellation cannot dispatch after %s departure, even if authority returns", async (departure) => {
    const net = hardwareHttp();
    const view = mountHardware(cancelPanel());
    const invalidate = vi.spyOn(view.client, "invalidateQueries");
    await openCancel();
    writeCancelReason("Departed private reason");
    onlineManager.setOnline(false);
    submitCancel();
    await paused(view.client);
    if (departure === "actor") login("B");
    view.rerender(departure === "unmount" ? <p>Left requests</p> : cancelPanel({
      makerspace: departure === "makerspace" ? { ...maker, id: 8, slug: "other" } : maker,
      canCancelRequests: departure !== "permission", guestOnly: departure === "guest",
    }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    if (departure !== "unmount") view.rerender(cancelPanel());
    await resume(view.client);
    expect(net.writes()).toHaveLength(0);
    expect(invalidate).not.toHaveBeenCalled();
    expect(screen.queryByText(/cancelled\.|Departed private reason|Request visit changed/)).not.toBeInTheDocument();
    if (departure !== "unmount") {
      await openCancel("Borrower B");
      expect(cancelReason()).toHaveValue("");
    }
  },
);

it.each([
  { departure: "permission", outcome: "success" },
  { departure: "permission", outcome: "error" },
  { departure: "guest", outcome: "success" },
  { departure: "guest", outcome: "error" },
])("late $outcome after $departure change cannot publish, clear or unlock the new cancellation", async ({ departure, outcome }) => {
  const first = held<Response>(); const second = held<Response>(); let posts = 0;
  const net = hardwareHttp((call) => call.path.endsWith("/cancel") ? (++posts === 1 ? first.promise : second.promise) : undefined);
  const view = mountHardware(cancelPanel());
  const invalidate = vi.spyOn(view.client, "invalidateQueries");
  await openCancel();
  writeCancelReason("A private reason");
  submitCancel();
  await waitFor(() => expect(net.writes()).toHaveLength(1));
  view.rerender(cancelPanel({ canCancelRequests: departure !== "permission", guestOnly: departure === "guest" }));
  view.rerender(cancelPanel());
  await openCancel("Borrower B");
  writeCancelReason("B private reason");
  submitCancel();
  await waitFor(() => expect(net.writes()).toHaveLength(2));
  await release(first, outcome === "success" ? json({ id: 1 }) : json({ detail: "Old cancellation failed" }, 409));
  expect(invalidate).not.toHaveBeenCalled();
  expect(screen.queryByText(/Request #1 cancelled\.|Old cancellation failed/)).not.toBeInTheDocument();
  expect(screen.getByRole("alertdialog", { name: "Cancel request #2?" })).toBeVisible();
  expect(cancelReason()).toBeDisabled();
  expect(cancelReason()).toHaveValue("B private reason");
  fireEvent.keyDown(document, { key: "Escape" });
  submitCancel();
  expect(net.writes()).toHaveLength(2);
  await release(second, json({ id: 2 }));
  await screen.findByText("Request #2 cancelled.");
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
});
