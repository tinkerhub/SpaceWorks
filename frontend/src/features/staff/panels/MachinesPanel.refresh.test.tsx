import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { PrinterPool } from "../../../generated/api";
import { serviceJob, serviceMachine, servicePool, setValue, type ConsoleKind } from "../../../test/staffServiceOwnershipHarness";
import { cleanUploadSession, held, http, json, release, resetUploadSession } from "../../../test/staffUploadHarness";
import { machineKeys, type Machine } from "../machinesApi";
import { poolQueryKey } from "./machine/servicePools";
import { mountQueuePanel, queueRead, queueTypes } from "./queueNavigationTestHarness";

beforeEach(() => resetUploadSession());
afterEach(() => cleanUploadSession());

describe.each<ConsoleKind>(["generic", "printer"])("%s explicit request refresh", (kind) => {
  it("refetches the current typed queue and observed canonical machine/pool caches while retaining edits", async () => {
    const gate = held<Response>();
    const type = queueTypes[kind === "printer" ? 1 : 0];
    let refresh = false;
    const machine = serviceMachine(type);
    const stock = servicePool(type);
    const net = http((call) => {
      if (call.path.includes("/requests?")) return refresh ? gate.promise : json([serviceJob(4, kind)]);
      if (call.path.endsWith("/machines")) return json({ count: 1, next: null,
        results: [{ ...machine, status: refresh ? "running" : "idle", usage_hours: refresh ? "1.25" : "0" }] });
      if (call.path.endsWith("/consumable-pools")) return json([{ ...stock, remaining_grams: refresh ? "725" : "800" }]);
      return queueRead(call);
    });
    const view = mountQueuePanel(`/admin/machines/${type.id}-${type.slug}/queue`);
    fireEvent.click(await screen.findByRole("button", { name: "Complete" }));
    setValue("Actual minutes", "37"); setValue("Manual usage note", "Still typing");
    await waitFor(() => expect(view.client.getQueryData<PrinterPool[]>(poolQueryKey(1))?.[0].remaining_grams).toBe("800"));
    refresh = true;
    fireEvent.click(screen.getByRole("button", { name: "Refresh requests" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Refresh requests" })).toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "Refresh requests" }));
    await waitFor(() => expect(net.calls.filter((call) => call.path.includes("/requests?"))).toHaveLength(2));
    // MachinesPanel supplies real active Query observers for both caches. These assertions
    // require the fresh HTTP data, not just an invalidateQueries spy or an invalidated flag.
    await waitFor(() => expect(view.client.getQueryData<{ results: Machine[] }>(machineKeys.list(1))?.results[0])
      .toMatchObject({ status: "running", usage_hours: "1.25" }));
    await waitFor(() => expect(view.client.getQueryData<PrinterPool[]>(poolQueryKey(1))?.[0].remaining_grams).toBe("725"));
    expect(screen.getByText("Job A", { exact: true })).toBeVisible();
    expect(screen.getByLabelText("Actual minutes")).toHaveValue("37");
    expect(screen.getByLabelText("Manual usage note")).toHaveValue("Still typing");
    await release(gate, json([{ ...serviceJob(4, kind), title: "Fresh server title" }]));
    expect(await screen.findByText("Fresh server title", { exact: true })).toBeVisible();
    await waitFor(() => expect(screen.getByRole("button", { name: "Refresh requests" })).toBeEnabled());
    expect(screen.getByLabelText("Actual minutes")).toHaveValue("37");
    expect(net.calls.filter((call) => call.path.includes("/requests?")).every((call) =>
      call.path === `/admin/makerspaces/1/machine-service/requests?machine_type_id=${type.id}`)).toBe(true);
  });

  it("keeps prior rows and an honest error on failed refresh, then retries without erasing drafts", async () => {
    let failed = false;
    const type = queueTypes[kind === "printer" ? 1 : 0];
    http((call) => call.path.includes("/requests?") && failed ? json({ detail: "Queue temporarily unavailable" }, 503) : queueRead(call, [serviceJob(4, kind)]));
    mountQueuePanel(`/admin/machines/${type.id}-${type.slug}/queue`);
    fireEvent.click(await screen.findByRole("button", { name: "Complete" }));
    setValue("Actual minutes", "37");
    failed = true;
    fireEvent.click(screen.getByRole("button", { name: "Refresh requests" }));
    expect(await screen.findByText("Queue temporarily unavailable")).toBeVisible();
    expect(screen.getByText("Job A", { exact: true })).toBeVisible();
    expect(screen.queryByText("The queue is clear")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Actual minutes")).toHaveValue("37");
    failed = false;
    fireEvent.click(screen.getByRole("button", { name: "Refresh requests" }));
    await waitFor(() => expect(screen.queryByText("Queue temporarily unavailable")).not.toBeInTheDocument());
    expect(screen.getByText("Job A", { exact: true })).toBeVisible();
    expect(screen.getByLabelText("Actual minutes")).toHaveValue("37");
  });
});
