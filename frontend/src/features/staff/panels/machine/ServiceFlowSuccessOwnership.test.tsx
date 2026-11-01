import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  ServiceConsoleHarness, filledServiceDraft, observedDraft, serviceMachine, serviceRead, serviceType, type ConsoleKind,
} from "../../../../test/staffServiceOwnershipHarness";
import { held, http, json, login, release } from "../../../../test/staffUploadHarness";
import { machineKeys } from "../../machinesApi";
import { flowLifecycle, mountFlow } from "./serviceFlowTestHarness";

flowLifecycle();

describe.each<ConsoleKind>(["generic", "printer"])("%s ownership during detail cancellation", (kind) => {
  describe.each(["queue", "manual"] as const)("%s success", (operation) => {
    it.each(["actor", "session", "resource"] as const)("rechecks ownership after awaited cancellation across a %s switch", async (change) => {
      const cancellation = held<void>();
      const bResponse = held<Response>();
      let posts = 0;
      const net = http((call) => call.method === "POST"
        ? (++posts === 1 ? json({ id: 4 }) : bResponse.promise) : serviceRead(call));
      const view = mountFlow(<ServiceConsoleHarness kind={kind} />);
      await screen.findByText("Job A", { exact: true });
      const detailKey = machineKeys.detail(77);
      view.client.setQueryDefaults(detailKey, { gcTime: Infinity, staleTime: Infinity });
      view.client.setQueryData(detailKey, serviceMachine(serviceType(kind), 77));
      const cancel = view.client.cancelQueries.bind(view.client);
      let cancelled = 0;
      // Preserve real cancellation; delay its completion to expose the async publication gap.
      vi.spyOn(view.client, "cancelQueries").mockImplementation(async (filters, options) => {
        await cancel(filters, options);
        if (++cancelled === 1) await cancellation.promise;
      });
      const submitName = operation === "queue" ? "Mark as failed" : "Log usage";
      const inputLabel = operation === "queue" ? "Actual minutes" : "Manual usage minutes";
      const toast = operation === "queue" ? "Job marked as failed" : kind === "printer" ? "Print logged" : "Usage logged";
      try {
        fireEvent.click(screen.getByRole("button", { name: submitName }));
        await waitFor(() => expect(cancelled).toBe(1));
        const aMutation = view.client.getMutationCache().getAll().find((mutation) => mutation.state.status === "pending")!;
        expect(aMutation).toBeDefined();
        expect(screen.getByLabelText(inputLabel)).toBeDisabled();
        expect(screen.queryByText(toast, { exact: true })).not.toBeInTheDocument();
        const next = filledServiceDraft(5);
        next.actionValues.reason = "B private reason";
        next.manual.note = "B private note";
        if (change !== "resource") login(change === "actor" ? "B" : "A");
        const typeId = change === "resource" ? 3 : undefined;
        view.rerender(<ServiceConsoleHarness kind={kind} typeId={typeId} replacement={next} />);
        await waitFor(() => expect(observedDraft()).toEqual(next));
        await screen.findByText("Job B", { exact: true });
        expect(screen.getByLabelText(inputLabel)).toBeEnabled();
        // This detail belongs to the replacement owner and must survive A's late continuation.
        const bDetail = { ...serviceMachine(serviceType(kind), 77), usage_hours: "9.25" };
        view.client.setQueryData(detailKey, bDetail);
        const bList = ["machine-service-requests", 1, typeId ?? serviceType(kind).id];
        expect(view.client.getQueryState(bList)?.isInvalidated).toBe(false);
        fireEvent.click(screen.getByRole("button", { name: submitName }));
        await waitFor(() => expect(posts).toBe(2));
        expect(screen.getByLabelText(inputLabel)).toBeDisabled();
        await release(cancellation, undefined);
        await waitFor(() => expect(aMutation.state.status).toBe("success"));
        expect(view.client.getQueryState(detailKey)?.isInvalidated).toBe(false);
        expect(view.client.getQueryData(detailKey)).toEqual(bDetail);
        expect(view.client.getQueryState(bList)?.isInvalidated).toBe(false);
        expect(observedDraft()).toEqual(next);
        expect(screen.queryByText(toast, { exact: true })).not.toBeInTheDocument();
        expect(screen.getByLabelText(inputLabel)).toBeDisabled();
        const pendingForm = screen.getByLabelText(inputLabel).closest("form")!;
        fireEvent.submit(pendingForm);
        fireEvent.change(screen.getByLabelText(inputLabel), { target: { value: "999" } });
        expect(net.writes()).toHaveLength(2);
        expect(observedDraft()).toEqual(next);
        await release(bResponse, json({ id: 5 }));
        await waitFor(() => expect(operation === "queue" ? observedDraft().action : observedDraft().manual.machine_id)
          .toBe(operation === "queue" ? null : ""));
        expect(await screen.findByText(toast, { exact: true })).toBeVisible();
        expect(view.client.getQueryState(detailKey)?.isInvalidated).toBe(true);
        await waitFor(() => expect(view.client.getMutationCache().getAll().every((mutation) => mutation.state.status !== "pending")).toBe(true));
      } finally {
        await release(cancellation, undefined);
        await release(bResponse, json({ id: 5 }));
      }
    });
  });
});
