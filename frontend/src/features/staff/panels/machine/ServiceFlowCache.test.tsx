import { QueryObserver } from "@tanstack/react-query";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  ServiceConsoleHarness, observedDraft, serviceMachine, serviceRead, serviceType, type ConsoleKind,
} from "../../../../test/staffServiceOwnershipHarness";
import { held, http, json, release } from "../../../../test/staffUploadHarness";
import { getMachine, machineKeys, type Machine } from "../../machinesApi";
import { flowLifecycle, mountFlow } from "./serviceFlowTestHarness";

flowLifecycle();

describe.each<ConsoleKind>(["generic", "printer"])("%s machine detail refresh", (kind) => {
  it.each(["queue", "manual"] as const)("%s success invalidates cached details and replaces an initial stale read", async (operation) => {
    const oldRead = held<Response>();
    const freshRead = held<Response>();
    const type = serviceType(kind);
    const old = { ...serviceMachine(type, 12), status: "running" as const, usage_hours: "0.00" };
    const fresh = { ...old, status: "idle" as const, usage_hours: "0.13" };
    let detailReads = 0;
    const net = http((call) => {
      if (call.path === "/admin/machines/12") return ++detailReads === 1 ? oldRead.promise : freshRead.promise;
      if (call.path === "/admin/machines/11") return json({ ...fresh, id: 11 });
      return serviceRead(call);
    });
    const view = mountFlow(<ServiceConsoleHarness kind={kind} />);
    await screen.findByText("Job A", { exact: true });
    const cachedKey = machineKeys.detail(11);
    const initialKey = machineKeys.detail(12);
    const unrelatedKeys = [["machine", 11, "history"], ["machine", "11"], ["machine-details", 11], ["members", 1]];
    for (const key of [cachedKey, ...unrelatedKeys]) {
      view.client.setQueryDefaults(key, { gcTime: Infinity, staleTime: Infinity });
      view.client.setQueryData(key, key === cachedKey ? { ...old, id: 11 } : { marker: "warm unrelated cache" });
    }
    const observer = new QueryObserver(view.client, {
      queryKey: initialKey, queryFn: () => getMachine(12), staleTime: Infinity,
    });
    const unsubscribe = observer.subscribe(() => undefined);
    try {
      await waitFor(() => expect(detailReads).toBe(1));
      expect(view.client.getQueryData(initialKey)).toBeUndefined();
      expect(observer.getCurrentResult().fetchStatus).toBe("fetching");
      fireEvent.click(screen.getByRole("button", { name: operation === "queue" ? "Mark as failed" : "Log usage" }));
      await waitFor(() => expect(net.writes()).toHaveLength(1));
      await waitFor(() => expect(view.client.getQueryState(cachedKey)?.isInvalidated).toBe(true));
      // The active initial read must be cancelled even though it has no cached data yet.
      await waitFor(() => expect(detailReads).toBe(2));
      // Success settlement waits for cancellation, but not the fresh detail network response.
      await waitFor(() => expect(operation === "queue" ? observedDraft().action : observedDraft().manual.machine_id)
        .toBe(operation === "queue" ? null : ""));
      expect(observer.getCurrentResult().data).toBeUndefined();
      expect(observer.getCurrentResult().fetchStatus).toBe("fetching");
      await release(freshRead, json(fresh));
      await waitFor(() => expect(observer.getCurrentResult().data).toEqual(fresh));
      expect(detailReads).toBe(2);
      expect(view.client.getQueryData(initialKey)).toEqual(fresh);
      expect(view.client.getQueryState(initialKey)?.isInvalidated).toBe(false);
      for (const key of unrelatedKeys) {
        expect(view.client.getQueryState(key)?.isInvalidated).toBe(false);
        expect(view.client.getQueryData(key)).toEqual({ marker: "warm unrelated cache" });
      }
      // Inactive detail data remains observable as stale until the drawer asks for it again.
      expect(view.client.getQueryData<Machine>(cachedKey)?.usage_hours).toBe("0.00");
      const next = await view.client.fetchQuery({ queryKey: cachedKey,
        queryFn: () => getMachine(11), staleTime: Infinity });
      expect(next).toMatchObject({ id: 11, status: "idle", usage_hours: "0.13" });
      expect(view.client.getQueryState(cachedKey)?.isInvalidated).toBe(false);
      await release(oldRead, json(old));
      expect(observer.getCurrentResult().data).toEqual(fresh);
      expect(view.client.getQueryData(initialKey)).toEqual(fresh);
      expect(await screen.findByText(operation === "queue" ? "Job marked as failed" : kind === "printer" ? "Print logged" : "Usage logged", { exact: true })).toBeVisible();
    } finally {
      unsubscribe();
      await release(freshRead, json(fresh));
      await release(oldRead, json(old));
    }
  });
});
