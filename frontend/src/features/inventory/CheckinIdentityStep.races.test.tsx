import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { lookupCheckin } = vi.hoisted(() => ({ lookupCheckin: vi.fn() }));
vi.mock("./api", async () => ({ ...await vi.importActual<typeof import("./api")>("./api"), lookupCheckin }));

import { nonNullConfirmations, renderCheckin, settleLookup, startLookup } from "../../test/checkinRegressionHarness";
import { deferred, rosterMatch } from "../../test/uiRegressionHarness";
import type { CheckinMatch } from "./api";

beforeEach(() => { lookupCheckin.mockReset(); });

describe("CheckinIdentityStep lookup races", () => {
  it("freezes input and rejects repeated Enter/button lookups while pending, retaining request ownership variables", async () => {
    const pending = deferred<CheckinMatch[]>();
    lookupCheckin.mockReturnValue(pending.promise);
    const { client } = renderCheckin();
    startLookup("  ada typed  ");
    const input = screen.getByLabelText(/your name/i);
    expect(input).toBeDisabled();
    fireEvent.change(input, { target: { value: "other person" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: /checking/i }));
    expect(input).toHaveValue("  ada typed  ");
    await waitFor(() => expect(lookupCheckin).toHaveBeenCalledTimes(1));
    expect(lookupCheckin).toHaveBeenCalledWith("a", "ada typed");
    expect(client.getMutationCache().getAll()).toHaveLength(1);
    expect(client.getMutationCache().getAll()[0].state.variables).toMatchObject({
      slug: "a", name: "ada typed", generation: expect.any(Number),
      context: { slug: "a", generation: expect.any(Number) }, lifetime: expect.any(Symbol),
    });
    await settleLookup(pending);
  });

  it.each(["success", "error"] as const)("ignores late A %s after switching to B", async (outcome) => {
    const old = deferred<CheckinMatch[]>();
    const fresh = deferred<CheckinMatch[]>();
    lookupCheckin.mockReturnValueOnce(old.promise).mockReturnValueOnce(fresh.promise);
    const view = renderCheckin();
    startLookup();
    await waitFor(() => expect(lookupCheckin).toHaveBeenCalledTimes(1));
    view.changeContext("b");
    expect(screen.getByLabelText(/your name/i)).toHaveValue("");
    startLookup("B person");
    await waitFor(() => expect(lookupCheckin).toHaveBeenCalledTimes(2));
    await act(async () => {
      if (outcome === "success") old.resolve([rosterMatch]);
      else old.reject(new Error("late A outage"));
    });
    expect(screen.getByLabelText(/your name/i)).toBeDisabled();
    expect(screen.queryByText(rosterMatch.name)).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(nonNullConfirmations(view.onConfirm)).toEqual([]);
    const b = { ...rosterMatch, mid: 900, name: "B Canonical" };
    await settleLookup(fresh, [b]);
    expect(view.onConfirm).toHaveBeenLastCalledWith(b);
  });

  it.each(["success", "error"] as const)("A→B→A rejects first A %s without unlocking or clearing the new A results", async (outcome) => {
    const old = deferred<CheckinMatch[]>();
    const fresh = deferred<CheckinMatch[]>();
    lookupCheckin.mockReturnValueOnce(old.promise).mockReturnValueOnce(fresh.promise);
    const view = renderCheckin();
    startLookup();
    await waitFor(() => expect(lookupCheckin).toHaveBeenCalledTimes(1));
    view.changeContext("b");
    view.changeContext("a");
    startLookup("new A intent");
    await waitFor(() => expect(lookupCheckin).toHaveBeenCalledTimes(2));
    const variables = view.client.getMutationCache().getAll().map((m) => m.state.variables as { context: object });
    expect(variables[0].context).not.toBe(variables[1].context);
    // Deliver the stale completion while the current visit owns the pending lock.
    await act(async () => {
      if (outcome === "success") old.resolve([rosterMatch]);
      else old.reject(new Error("first A failed"));
    });
    expect(screen.getByLabelText(/your name/i)).toBeDisabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(nonNullConfirmations(view.onConfirm)).toEqual([]);
    const matches = [
      { ...rosterMatch, mid: 701, name: "New A One" },
      { ...rosterMatch, mid: 702, name: "New A Two" },
    ];
    await settleLookup(fresh, matches);
    expect(screen.getByText("New A One")).toBeInTheDocument();
    expect(screen.getByText("New A Two")).toBeInTheDocument();
    expect(screen.queryByText(rosterMatch.name)).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "That's me" })[1]);
    expect(view.onConfirm).toHaveBeenLastCalledWith(matches[1]);
  });

  it("a late first A success cannot replace already settled new A matches", async () => {
    const old = deferred<CheckinMatch[]>();
    lookupCheckin.mockReturnValueOnce(old.promise).mockResolvedValueOnce([
      { ...rosterMatch, mid: 801, name: "Current A One" },
      { ...rosterMatch, mid: 802, name: "Current A Two" },
    ]);
    const view = renderCheckin();
    startLookup();
    await waitFor(() => expect(lookupCheckin).toHaveBeenCalledTimes(1));
    view.changeContext("b");
    view.changeContext("a");
    startLookup("current");
    await screen.findByText("Current A Two");
    await act(async () => old.resolve([rosterMatch]));
    expect(screen.getByText("Current A One")).toBeInTheDocument();
    expect(screen.queryByText(rosterMatch.name)).not.toBeInTheDocument();
    expect(nonNullConfirmations(view.onConfirm)).toEqual([]);
  });
});
