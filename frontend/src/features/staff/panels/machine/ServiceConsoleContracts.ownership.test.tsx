import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { onlineManager } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ServiceConsoleHarness, filledServiceDraft, observedDraft, serviceJob, serviceRead,
  type ConsoleKind,
} from "../../../../test/staffServiceOwnershipHarness";
import { cleanUploadSession, held, http, json, login, mountStaff, release, resetUploadSession } from "../../../../test/staffUploadHarness";

let originalOnline: boolean;
beforeEach(() => { originalOnline = onlineManager.isOnline(); resetUploadSession(); });
afterEach(() => { onlineManager.setOnline(originalOnline); cleanUploadSession(); });

describe.each<ConsoleKind>(["generic", "printer"])("%s service payload controls", (kind) => {
  it.each(["accept", "start"] as const)("%s preserves immutable job/action identity and quantity/grams contract", async (name) => {
    const draft = filledServiceDraft();
    draft.action = { id: 4, name };
    draft.actionValues = { ...draft.actionValues, consumable_pool_id: "31", estimated_minutes: "45", planned_quantity: "9.75" };
    const net = http((call) => call.path.includes("/requests?") ? json([{ ...serviceJob(4, kind), status: name === "accept" ? "pending" : "accepted" }]) : serviceRead(call));
    const view = mountStaff(<ServiceConsoleHarness kind={kind} initial={draft} />);
    await screen.findByText("Job A");
    onlineManager.setOnline(false);
    fireEvent.click(screen.getByRole("button", { name: name === "accept" ? "Accept job" : "Start job" }));
    await waitFor(() => expect(view.client.getMutationCache().getAll().some((mutation) => mutation.state.isPaused)).toBe(true));
    // Same context, newer immutable values: queued dispatch must retain the admitted body.
    const next = { ...draft, actionValues: { ...draft.actionValues, planned_quantity: "99", estimated_minutes: "99" } };
    view.rerender(<ServiceConsoleHarness kind={kind} initial={draft} replacement={next} />);
    await waitFor(() => expect(observedDraft().actionValues.estimated_minutes).toBe("99"));
    await act(async () => { onlineManager.setOnline(true); await view.client.resumePausedMutations(); });
    expect(net.writes()).toHaveLength(1);
    expect(net.writes()[0].path).toBe(`/admin/machine-service/requests/4/${name}`);
    expect(net.writes()[0].body).toEqual({ estimated_minutes: 45,
      ...(name === "start" ? { machine_id: 11, ...(kind === "printer" ? { consumable_pool_id: 31 } : {}) } : {}),
      ...(kind === "printer" ? { planned_grams: "9.75" } : name === "start" ? { planned_quantity: "9.75" } : {}),
    });
  });

  it.each(["collect", "record-manual-payment"] as const)("current %s retains collection/payment/report/fleet invalidations", async (name) => {
    const draft = filledServiceDraft(); draft.action = { id: 4, name };
    const job = { ...serviceJob(4, kind), status: "completed", payment: name === "record-manual-payment" ? {
      id: 51, subject_type: "machine_service_request", subject_label: "Job A", status: "pending", checkout_url: "", created_at: "", amount: "14.50", currency: "inr",
    } : null };
    const net = http((call) => call.path.includes("/requests?") ? json([job]) : serviceRead(call));
    const view = mountStaff(<ServiceConsoleHarness kind={kind} initial={draft} />);
    await screen.findByText("Job A");
    const invalidate = vi.spyOn(view.client, "invalidateQueries");
    fireEvent.click(screen.getByRole("button", { name: name === "collect" ? "Mark collected" : "Record payment" }));
    await waitFor(() => expect(observedDraft().action).toBeNull());
    expect(net.writes()[0]).toMatchObject({ path: `/admin/machine-service/requests/4/${name}`, body: {} });
    const keys = invalidate.mock.calls.map(([filters]) => filters?.queryKey);
    expect(keys).toEqual(expect.arrayContaining([["machine-service-handover", 1], ["operations-report"], ["machine-service-pools", 1], ["machines", 1]]));
    if (name === "record-manual-payment") expect(keys).toEqual(expect.arrayContaining([
      ["payments", 1], ["operations-report", "payment-reconciliation"], ["dashboard", 1], ["machine-service-requests", 1], ["members", 1],
    ]));
    expect(await screen.findByText(name === "collect" ? "Job collected" : "Payment recorded")).toBeVisible();
  });

  it("current manual error survives finish and explicit retry preserves its price/percent input", async () => {
    let fail = true;
    const net = http((call) => call.method === "POST" && fail ? json({ detail: "Manual run unavailable" }, 503) : serviceRead(call));
    mountStaff(<ServiceConsoleHarness kind={kind} />);
    await screen.findByText("Job A");
    fireEvent.click(screen.getByRole("button", { name: "Log usage" }));
    await screen.findAllByText("Manual run unavailable");
    await waitFor(() => expect(screen.getByRole("button", { name: "Log usage" })).toBeEnabled());
    expect(observedDraft().manual).toMatchObject({ price: "12.50", percent_complete: "40", note: "Click-time note" });
    expect(screen.getAllByText("Manual run unavailable").length).toBeGreaterThan(0);
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Log usage" }));
    await waitFor(() => expect(observedDraft().manual.machine_id).toBe(""));
    expect(net.writes()).toHaveLength(2);
    expect(net.writes()[1].body).toEqual(net.writes()[0].body);
    expect(await screen.findByText(kind === "printer" ? "Print logged" : "Usage logged")).toBeVisible();
  });
});

it.each(["resource", "action", "unmount"])("paused queue ID/name cannot dispatch after %s changes", async (change) => {
  const net = http(serviceRead);
  const view = mountStaff(<ServiceConsoleHarness />);
  await screen.findByText("Job A");
  onlineManager.setOnline(false);
  fireEvent.click(screen.getByRole("button", { name: "Mark as failed" }));
  await waitFor(() => expect(view.client.getMutationCache().getAll().some((mutation) => mutation.state.isPaused)).toBe(true));
  if (change === "action") {
    const next = filledServiceDraft(5); next.action = { id: 5, name: "complete" };
    view.rerender(<ServiceConsoleHarness replacement={next} />);
    await waitFor(() => expect(observedDraft().action).toEqual({ id: 5, name: "complete" }));
  } else if (change === "resource") view.rerender(<ServiceConsoleHarness typeId={3} />);
  else view.unmount();
  await act(async () => { onlineManager.setOnline(true); await view.client.resumePausedMutations(); });
  expect(net.writes()).toHaveLength(0);
  expect(screen.queryByText(/This service action is no longer current/)).not.toBeInTheDocument();
});

it.each(["actor", "resource", "unmount"])("paused manual usage cannot dispatch after %s departure", async (change) => {
  const net = http(serviceRead);
  const view = mountStaff(<ServiceConsoleHarness />);
  await screen.findByText("Job A");
  onlineManager.setOnline(false);
  fireEvent.click(screen.getByRole("button", { name: "Log usage" }));
  await waitFor(() => expect(view.client.getMutationCache().getAll().some((mutation) => mutation.state.isPaused)).toBe(true));
  if (change === "actor") { login("B"); view.rerender(<ServiceConsoleHarness />); }
  else if (change === "resource") view.rerender(<ServiceConsoleHarness typeId={3} />);
  else view.unmount();
  await act(async () => { onlineManager.setOnline(true); await view.client.resumePausedMutations(); });
  expect(net.writes()).toHaveLength(0);
  expect(screen.queryByText("Usage logged")).not.toBeInTheDocument();
});

it.each(["success", "error"])("already-dispatched A manual %s/finally cannot erase B or unlock B's run", async (outcome) => {
  const a = held<Response>(); const b = held<Response>(); let posts = 0;
  const net = http((call) => call.method === "POST" ? (++posts === 1 ? a.promise : b.promise) : serviceRead(call));
  const view = mountStaff(<ServiceConsoleHarness />);
  await screen.findByText("Job A");
  fireEvent.click(screen.getByRole("button", { name: "Log usage" }));
  await waitFor(() => expect(posts).toBe(1));
  const next = filledServiceDraft(5); next.manual.note = "B private note";
  view.rerender(<ServiceConsoleHarness typeId={3} replacement={next} />);
  await waitFor(() => expect(observedDraft().manual.note).toBe("B private note"));
  fireEvent.click(screen.getByRole("button", { name: "Log usage" }));
  await waitFor(() => expect(posts).toBe(2));
  expect(screen.getByLabelText("Actual minutes")).toBeEnabled(); // Independent queue owner remains usable.
  await release(a, outcome === "success" ? json({ id: 4 }) : json({ detail: "A manual rejected" }, 409));
  expect(observedDraft()).toEqual(next);
  expect(screen.getByLabelText("Manual usage minutes")).toBeDisabled();
  expect(screen.queryByText(/A manual rejected|Usage logged/)).not.toBeInTheDocument();
  fireEvent.submit(screen.getByRole("button", { name: "Logging…" }).closest("form")!);
  expect(net.writes()).toHaveLength(2);
  await release(b, json({ id: 5 }));
  await waitFor(() => expect(observedDraft().manual.machine_id).toBe(""));
});
