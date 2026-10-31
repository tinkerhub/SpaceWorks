import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { onlineManager } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ServiceConsoleHarness, filledServiceDraft, observedDraft, serviceRead, setValue,
  type ConsoleKind,
} from "../../../../test/staffServiceOwnershipHarness";
import { cleanUploadSession, held, http, json, login, mountStaff, release, resetUploadSession } from "../../../../test/staffUploadHarness";

let originalOnline: boolean;
beforeEach(() => { originalOnline = onlineManager.isOnline(); resetUploadSession(); });
afterEach(() => { onlineManager.setOnline(originalOnline); cleanUploadSession(); });

describe.each<ConsoleKind>(["generic", "printer"])("%s service action admission", (kind) => {
  it("paused queue/manual keep click-time bodies, synchronous edit/duplicate guards, and independent owners", async () => {
    const net = http(serviceRead);
    const view = mountStaff(<ServiceConsoleHarness kind={kind} />);
    await screen.findByText("Job A");
    onlineManager.setOnline(false);
    const queueForm = screen.getByRole("button", { name: "Mark as failed" }).closest("form")!;
    const manualForm = screen.getByRole("button", { name: "Log usage" }).closest("form")!;
    const jobB = screen.getByText("Job B").closest("article")!;
    act(() => {
      fireEvent.submit(queueForm);
      setValue("Actual minutes", "999");
      fireEvent.click(within(jobB).getByRole("button", { name: "Complete" }));
      fireEvent.submit(queueForm);
    });
    expect(observedDraft().action).toEqual({ id: 4, name: "fail" });
    expect(observedDraft().actionValues.actual_minutes).toBe("23");
    // A queue task must not lock the independent manual operation.
    expect(screen.getByLabelText("Manual usage minutes")).toBeEnabled();
    act(() => {
      fireEvent.submit(manualForm);
      setValue("Manual usage note", "blocked after admission");
      fireEvent.submit(manualForm);
    });
    await waitFor(() => expect(view.client.getMutationCache().getAll().filter((m) => m.state.isPaused)).toHaveLength(2));
    expect(net.writes()).toHaveLength(0);
    expect(screen.getByLabelText("Actual minutes")).toBeDisabled();
    expect(screen.getByLabelText("Manual usage minutes")).toBeDisabled();
    expect(observedDraft().manual.note).toBe("Click-time note");
    // Simulate an immutable cache/parent update while TanStack has not dispatched yet.
    const external = filledServiceDraft();
    external.actionValues = { ...external.actionValues, actual_quantity: "99", actual_minutes: "99", reason: "later reason" };
    external.manual = { ...external.manual, quantity: "99", duration_minutes: "99", note: "external edit", price: "99" };
    view.rerender(<ServiceConsoleHarness kind={kind} replacement={external} />);
    await waitFor(() => expect(observedDraft().manual.note).toBe("external edit"));
    await act(async () => { onlineManager.setOnline(true); await view.client.resumePausedMutations(); });
    await waitFor(() => expect(net.writes()).toHaveLength(2));
    expect(net.writes().find((call) => call.path === "/admin/machine-service/requests/4/fail")?.body).toEqual({
      actual_minutes: 23, [kind === "printer" ? "actual_grams" : "actual_quantity"]: "4.5", percent_complete: 35, reason: "Broken fixture",
    });
    expect(net.writes().find((call) => call.path.endsWith("/typed-manual-usage"))?.body).toEqual({
      machine_id: 11, consumable_pool_id: null, duration_minutes: 17,
      [kind === "printer" ? "grams" : "quantity"]: "2.25", ...(kind === "generic" ? { metering_unit: "count" } : {}),
      outcome: "failed", percent_complete: 40, reason: "Jam", note: "Click-time note", price: "12.50",
    });
    expect(observedDraft()).toEqual(external); // Successful old compositions cannot erase newer typing.
    await waitFor(() => expect(screen.getByLabelText("Manual usage minutes")).toBeEnabled());
  });

  it("paused queue dispatch never sends the old job ID using a new actor", async () => {
    const net = http(serviceRead);
    const view = mountStaff(<ServiceConsoleHarness kind={kind} />);
    await screen.findByText("Job A");
    onlineManager.setOnline(false);
    fireEvent.click(screen.getByRole("button", { name: "Mark as failed" }));
    await waitFor(() => expect(view.client.getMutationCache().getAll().some((m) => m.state.isPaused)).toBe(true));
    login("B");
    const next = filledServiceDraft(5);
    view.rerender(<ServiceConsoleHarness kind={kind} replacement={next} />);
    await waitFor(() => expect(observedDraft().action?.id).toBe(5));
    await act(async () => { onlineManager.setOnline(true); await view.client.resumePausedMutations(); });
    expect(net.writes()).toHaveLength(0);
    expect(observedDraft().action?.id).toBe(5);
    expect(screen.queryByText(/This service action is no longer current/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Mark as failed" }));
    await waitFor(() => expect(net.writes()).toHaveLength(1));
    expect(net.writes()[0].path).toBe("/admin/machine-service/requests/5/fail");
  });

  it("current failure remains visible after finish, retry works, and successful queue/manual reset only their own drafts", async () => {
    let fail = true;
    const net = http((call) => call.method === "POST" && fail ? json({ detail: "Machine temporarily busy" }, 409) : serviceRead(call));
    const view = mountStaff(<ServiceConsoleHarness kind={kind} />);
    await screen.findByText("Job A");
    fireEvent.click(screen.getByRole("button", { name: "Mark as failed" }));
    await screen.findAllByText("Machine temporarily busy");
    await waitFor(() => expect(screen.getByRole("button", { name: "Mark as failed" })).toBeEnabled());
    expect(observedDraft().action).toEqual({ id: 4, name: "fail" });
    expect(screen.getAllByText("Machine temporarily busy").length).toBeGreaterThan(0);
    fail = false;
    const invalidate = vi.spyOn(view.client, "invalidateQueries");
    fireEvent.click(screen.getByRole("button", { name: "Mark as failed" }));
    await waitFor(() => expect(observedDraft().action).toBeNull());
    expect(observedDraft().manual.note).toBe("Click-time note");
    expect(await screen.findByText("Job marked as failed")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Log usage" }));
    await waitFor(() => expect(observedDraft().manual.machine_id).toBe(""));
    expect(await screen.findByText(kind === "printer" ? "Print logged" : "Usage logged")).toBeVisible();
    const keys = invalidate.mock.calls.map(([filters]) => filters?.queryKey);
    expect(keys).toEqual(expect.arrayContaining([
      ["machine-service-requests", 1, kind === "printer" ? 2 : 1], ["machine-service-manual", 1, kind === "printer" ? 2 : 1],
      ["machine-service-handover", 1], ["operations-report"], ["machine-service-report", 1], ["printer-service-report", 1],
      ["machine-service-pools", 1], ["machines", 1],
    ]));
    expect(net.writes()).toHaveLength(3);
  });
});

it.each(["success", "error"])("already-dispatched A queue %s/finally cannot clear B or unlock B pending action", async (outcome) => {
  const responseA = held<Response>(); const responseB = held<Response>();
  let writes = 0;
  const net = http((call) => call.method === "POST" ? (++writes === 1 ? responseA.promise : responseB.promise) : serviceRead(call));
  const view = mountStaff(<ServiceConsoleHarness />);
  await screen.findByText("Job A");
  fireEvent.click(screen.getByRole("button", { name: "Mark as failed" }));
  await waitFor(() => expect(writes).toBe(1));
  const next = filledServiceDraft(5);
  next.actionValues.reason = "B private reason";
  view.rerender(<ServiceConsoleHarness typeId={3} replacement={next} />);
  await waitFor(() => expect(observedDraft().action?.id).toBe(5));
  fireEvent.click(await screen.findByRole("button", { name: "Mark as failed" }));
  await waitFor(() => expect(writes).toBe(2));
  await release(responseA, outcome === "success" ? json({ id: 4 }) : json({ detail: "Old A rejected" }, 409));
  expect(observedDraft()).toEqual(next);
  expect(screen.getByLabelText("Actual minutes")).toBeDisabled();
  expect(screen.queryByText(/Old A rejected|Job marked as failed/)).not.toBeInTheDocument();
  fireEvent.submit(screen.getByRole("button", { name: "Saving…" }).closest("form")!);
  expect(net.writes()).toHaveLength(2);
  await release(responseB, json({ id: 5 }));
  await waitFor(() => expect(observedDraft().action).toBeNull());
});
