import { onlineManager, type Mutation, type QueryClient } from "@tanstack/react-query";
import { act, cleanup, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { lookupCheckin } = vi.hoisted(() => ({ lookupCheckin: vi.fn() }));
vi.mock("./api", async () => ({ ...await vi.importActual<typeof import("./api")>("./api"), lookupCheckin }));

import { nonNullConfirmations, renderCheckin, startLookup } from "../../test/checkinRegressionHarness";
import { rosterMatch } from "../../test/uiRegressionHarness";

let previousOnline: boolean;

beforeEach(() => {
  previousOnline = onlineManager.isOnline();
  onlineManager.setOnline(false);
  lookupCheckin.mockReset();
  // The leaf transport has no ownership logic: any dispatch would return a match.
  lookupCheckin.mockResolvedValue([rosterMatch]);
});

afterEach(() => {
  // Unmount before restoring the singleton, including when an assertion fails.
  cleanup();
  onlineManager.setOnline(previousOnline);
});

async function queueLookup(client: QueryClient, name = "ada typed") {
  startLookup(name);
  await waitFor(() => {
    const mutations = client.getMutationCache().getAll();
    expect(mutations).toHaveLength(1);
    expect(mutations[0].state).toMatchObject({ status: "pending", isPaused: true });
  });
  const mutation = client.getMutationCache().getAll()[0];
  expect(mutation.state.variables).toMatchObject({ slug: "a", name: name.trim() });
  expect(screen.getByLabelText(/your name/i)).toBeDisabled();
  expect(screen.getByRole("button", { name: /checking/i })).toBeDisabled();
  expect(lookupCheckin).not.toHaveBeenCalled();
  return mutation;
}

async function resumeAndSettle(client: QueryClient, mutation: Mutation, status: "success" | "error") {
  await act(async () => {
    onlineManager.setOnline(true);
    // Explicitly resume this client too: unmount removes its online subscription.
    await client.resumePausedMutations();
  });
  // Resuming alone is insufficient: wait through onSuccess/onError/onSettled.
  await waitFor(() => expect(mutation.state).toMatchObject({ status, isPaused: false }));
}

function expectNoPublishedLookup(onConfirm: ReturnType<typeof vi.fn>) {
  expect(nonNullConfirmations(onConfirm)).toEqual([]);
  expect(screen.queryByText(rosterMatch.name)).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "That's me" })).not.toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
}

describe("CheckinIdentityStep queued dispatch", () => {
  it("dispatches and confirms a still-current queued lookup after reconnect", async () => {
    const view = renderCheckin();
    const queued = await queueLookup(view.client, "  ada typed  ");

    await resumeAndSettle(view.client, queued, "success");

    expect(lookupCheckin).toHaveBeenCalledExactlyOnceWith("a", "ada typed");
    expect(nonNullConfirmations(view.onConfirm)).toEqual([[rosterMatch]]);
    expect(screen.getByText(rosterMatch.name)).toBeInTheDocument();
    expect(screen.getByLabelText(/your name/i)).toBeEnabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it.each([
    { visit: "A→B", slugs: ["b"] },
    { visit: "A→B→A", slugs: ["b", "a"] },
  ])("rejects the queued first A before transport after $visit", async ({ slugs }) => {
    const view = renderCheckin();
    const queued = await queueLookup(view.client);

    for (const slug of slugs) view.changeContext(slug);
    expect(screen.getByLabelText(/your name/i)).toHaveValue("");

    await resumeAndSettle(view.client, queued, "error");

    expect(lookupCheckin).not.toHaveBeenCalled();
    expectNoPublishedLookup(view.onConfirm);
    expect(screen.getByLabelText(/your name/i)).toBeEnabled();
    expect(screen.getByLabelText(/your name/i)).toHaveValue("");
    expect(view.client.getMutationCache().getAll()).toHaveLength(1);
  });

  it("rejects a queued lookup before transport after unmount", async () => {
    const view = renderCheckin();
    const queued = await queueLookup(view.client);
    const confirmationsBeforeUnmount = [...view.onConfirm.mock.calls];

    view.unmount();
    await resumeAndSettle(view.client, queued, "error");

    expect(lookupCheckin).not.toHaveBeenCalled();
    expect(view.onConfirm.mock.calls).toEqual(confirmationsBeforeUnmount);
    expect(screen.queryByLabelText(/your name/i)).not.toBeInTheDocument();
  });

  it("rejects disabled queued dispatch and releases pending while disabled before reenable retry", async () => {
    const view = renderCheckin();
    const queued = await queueLookup(view.client);

    view.changeContext("a", true);
    expect(screen.getByRole("button", { name: /checking/i })).toBeDisabled();
    await resumeAndSettle(view.client, queued, "error");

    expect(lookupCheckin).not.toHaveBeenCalled();
    expectNoPublishedLookup(view.onConfirm);
    // The external disabled flag still applies, but this lookup's pending lock is gone.
    await waitFor(() => expect(screen.queryByRole("button", { name: /checking/i })).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Find me" })).toBeDisabled();
    expect(screen.getByLabelText(/your name/i)).toBeDisabled();
    expect(screen.getByLabelText(/your name/i)).toHaveValue("ada typed");

    view.changeContext("a");
    expect(screen.getByLabelText(/your name/i)).toBeEnabled();
    expect(screen.getByRole("button", { name: "Find me" })).toBeEnabled();
    startLookup("fresh name");
    await waitFor(() => {
      const mutations = view.client.getMutationCache().getAll();
      expect(mutations).toHaveLength(2);
      expect(mutations[1].state.status).toBe("success");
    });

    expect(lookupCheckin).toHaveBeenCalledExactlyOnceWith("a", "fresh name");
    expect(nonNullConfirmations(view.onConfirm)).toEqual([[rosterMatch]]);
    expect(screen.getByLabelText(/your name/i)).toBeEnabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
