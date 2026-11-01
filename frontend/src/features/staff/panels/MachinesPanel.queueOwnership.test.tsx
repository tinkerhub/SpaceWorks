import { QueryClient } from "@tanstack/react-query";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { serviceJob, setValue, type ConsoleKind } from "../../../test/staffServiceOwnershipHarness";
import { cleanUploadSession, held, http, json, release, resetUploadSession } from "../../../test/staffUploadHarness";
import { mountQueuePanel, queryDataReady, queueRead, queueTypes } from "./queueNavigationTestHarness";

beforeEach(() => resetUploadSession());
afterEach(() => cleanUploadSession());

describe.each<ConsoleKind>(["generic", "printer"])("%s queue visit ownership", (kind) => {
  it.each([false, true])("leaving for equipment revokes a pending response, including late failure=%s", async (fail) => {
    const old = held<Response>();
    const type = queueTypes[kind === "printer" ? 1 : 0];
    let version = 0;
    const net = http((call) => {
      if (call.method === "POST") return old.promise;
      return queueRead(call, [{ ...serviceJob(4, kind), title: version ? "Server updated job" : "Job A" }]);
    });
    // Preserve a FRESH typed cache across equipment navigation. A new visit still must
    // refetch, even though an ordinary stale-only mount would reuse these rows forever.
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity, gcTime: Infinity }, mutations: { retry: false } } });
    const view = mountQueuePanel(`/admin/machines/${type.id}-${type.slug}/queue`, {}, client);
    try {
      // Wait for the actual scoped HTTP query, rather than spending a DOM query's budget
      // on cold catalog/queue loading. No cache is seeded and all dispatch checks remain.
      await act(async () => { await queryDataReady(client, ["machine-service-requests", 1, type.id]); });
      fireEvent.click(await screen.findByRole("button", { name: "Complete" }));
      setValue("Actual minutes", "37");
      setValue("Manual usage note", "Keep my manual draft");
      const form = screen.getByRole("button", { name: "Complete job" }).closest("form")!;
      act(() => { fireEvent.submit(form); fireEvent.submit(form); });
      await waitFor(() => expect(net.writes()).toHaveLength(1));
      await waitFor(() => expect(screen.getByLabelText("Actual minutes")).toBeDisabled());
      fireEvent.submit(form);
      expect(net.writes()).toHaveLength(1);
      const mutation = client.getMutationCache().getAll().find((entry) => entry.state.status === "pending")!;
      fireEvent.click(screen.getByRole("link", { name: "Machines & stock" }));
      expect(screen.queryByLabelText("Actual minutes")).not.toBeInTheDocument();
      expect(client.getQueryData(["machine-service-requests", 1, type.id])).toBeDefined();
      version = 1;
      fireEvent.click(screen.getByRole("button", { name: "Browser back" }));
      expect(await screen.findByText("Server updated job", { exact: true })).toBeVisible();
      expect(screen.getByLabelText("Actual minutes")).toHaveValue("37");
      expect(screen.getByLabelText("Manual usage note")).toHaveValue("Keep my manual draft");
      expect(screen.getByLabelText("Actual minutes")).toBeEnabled();
      setValue("Actual minutes", "51");
      const readsBeforeSettlement = net.calls.filter((call) => call.method === "GET").length;
      await release(old, fail ? json({ detail: "Obsolete completion refused" }, 409) : json({ id: 4 }));
      await waitFor(() => expect(mutation.state.status).toBe(fail ? "error" : "success"));
      expect(screen.getByLabelText("Actual minutes")).toHaveValue("51");
      expect(screen.getByLabelText("Manual usage note")).toHaveValue("Keep my manual draft");
      expect(screen.queryByText("Job completed", { exact: true })).not.toBeInTheDocument();
      expect(screen.queryByText(/Obsolete completion refused|Couldn.t complete the job/)).not.toBeInTheDocument();
      expect(net.calls.filter((call) => call.method === "GET")).toHaveLength(readsBeforeSettlement);
      expect(net.writes()).toHaveLength(1);
      expect(net.calls.filter((call) => call.path.includes("/requests?"))).toHaveLength(2);
    } finally {
      view.unmount(); client.clear();
      await release(old, json({ id: 4 }));
    }
  });
});
