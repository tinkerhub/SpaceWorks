import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  endHardwareTest, hardwareHttp, json, maker, mountHardware, page, requestA, startHardwareTest,
} from "../../../test/hardwareOwnershipHarness";
import { cancelPanel, openCancel, submitCancel, writeCancelReason } from "../../../test/cancelRequestHarness";

beforeEach(startHardwareTest);
afterEach(endHardwareTest);

it("only accepted wholly unissued rows offer Cancel, including defensive handling of unexpected queue rows", async () => {
  const ineligible = [
    { ...requestA, id: 2, requester_username: "Already issued", items: requestA.items.map((item) => ({ ...item, issued_quantity: 1 })) },
    { ...requestA, id: 3, requester_username: "Returned borrower", status: "returned" },
    { ...requestA, id: 4, requester_username: "Pending borrower", status: "pending_approval" },
  ];
  hardwareHttp((call) => call.path.includes("/accepted-requests") ? json(page([requestA, ...ineligible])) : undefined, []);
  mountHardware(cancelPanel());
  await screen.findByText("Already issued");
  expect(screen.getAllByRole("button", { name: "Cancel request…" })).toHaveLength(1);
  for (const row of ineligible) {
    const tableRow = screen.getByText(row.requester_username).closest("tr")!;
    expect(within(tableRow).queryByRole("button", { name: "Cancel request…" })).not.toBeInTheDocument();
  }
});

it("successful cancellation refreshes origin queues, history, dashboard, stock, public catalogue and containers", async () => {
  let cancelled = false;
  const closed = { ...requestA, status: "cancelled", cancellation_reason: "Changed plans" };
  hardwareHttp((call) => {
    if (call.path.endsWith("/cancel")) { cancelled = true; return json(closed); }
    if (call.path.includes("/accepted-requests")) return json(page(cancelled ? [] : [requestA]));
    if (call.path.includes("/request-history")) return json(page(cancelled ? [closed] : []));
    return undefined;
  });
  const view = mountHardware(cancelPanel());
  const invalidate = vi.spyOn(view.client, "invalidateQueries");
  const clear = vi.spyOn(view.client, "clear");
  const otherKeys = ["accepted", "request-history", "dashboard", "inventory", "containers"].map((key) => [key, 8]);
  otherKeys.push(["public-stats", "other"]);
  for (const key of otherKeys) {
    view.client.setQueryDefaults(key, { gcTime: Infinity });
    view.client.setQueryData(key, { untouched: true });
  }
  fireEvent.click(await screen.findByRole("button", { name: "Show history" }));
  await screen.findByText("Returned, rejected, cancelled and closed requests show up here.");
  await openCancel();
  writeCancelReason("Changed plans");
  submitCancel();
  await screen.findByText("Request #1 cancelled.");
  await screen.findByText("Cancelled");
  await waitFor(() => expect(screen.queryByRole("button", { name: "Cancel request…" })).not.toBeInTheDocument());
  const keys = invalidate.mock.calls.map(([filters]) => filters?.queryKey);
  for (const key of [
    ["pending", maker.id], ["accepted", maker.id], ["active", maker.id], ["request-history", maker.id],
    ["dashboard", maker.id], ["inventory", maker.id], ["inventory-all", maker.id],
    ["containers", maker.id], ["containers-all", maker.id],
    ["public-inventory"], ["public-inventory-detail"], ["public-stats", maker.slug],
    ["public-categories", maker.slug], ["tenant-bootstrap", maker.slug],
  ]) expect(keys).toContainEqual(key);
  expect(keys.some((key) => key?.includes(8) || key?.includes("other"))).toBe(false);
  for (const key of otherKeys) {
    expect(view.client.getQueryState(key)?.isInvalidated).toBe(false);
    expect(view.client.getQueryData(key)).toEqual({ untouched: true });
  }
  expect(clear).not.toHaveBeenCalled();
});

it("history detail shows staff cancellation reason, actor and time with a neutral terminal status", async () => {
  const closedAt = "2026-10-30T10:30:00Z";
  const row = { ...requestA, status: "cancelled", cancellation_reason: "Borrower no longer needs the scope",
    closed_by: { username: "reviewer-amy", role: "Custom reviewer" }, closed_at: closedAt };
  hardwareHttp((call) => call.path.includes("/request-history") ? json(page([row])) : undefined, []);
  mountHardware(cancelPanel());
  fireEvent.click(await screen.findByRole("button", { name: "Show history" }));
  const details = await screen.findByRole("button", { name: "Details for request #1" });
  const tableRow = details.closest("tr")!;
  expect(within(tableRow).getByText("Cancelled")).toBeVisible();
  expect(within(tableRow).getByText("Cancelled").parentElement).toHaveClass("bg-fill", "text-ink-secondary");
  expect(within(tableRow).queryByRole("button", { name: /Cancel request/ })).not.toBeInTheDocument();
  fireEvent.click(details);
  const drawer = within(screen.getByRole("dialog", { name: "Request #1" }));
  expect(drawer.getByText("Cancelled because").nextElementSibling).toHaveTextContent(row.cancellation_reason);
  expect(drawer.getByText("Cancelled by").nextElementSibling).toHaveTextContent("reviewer-amy (Custom reviewer)");
  expect(drawer.getByText("Cancelled at").nextElementSibling).toHaveTextContent(
    new Date(closedAt).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }),
  );
  const progress = drawer.getByRole("navigation", { name: "Request status: Cancelled" });
  expect(progress).toHaveTextContent("Cancelled");
  expect(within(progress).queryByRole("list")).not.toBeInTheDocument();
  expect(drawer.queryByText("Collected")).not.toBeInTheDocument();
  expect(drawer.queryByText("Requested")).not.toBeInTheDocument();
});
