import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { lookupCheckin } = vi.hoisted(() => ({ lookupCheckin: vi.fn() }));
vi.mock("./api", async () => ({ ...await vi.importActual<typeof import("./api")>("./api"), lookupCheckin }));

import { nonNullConfirmations, renderCheckin, startLookup } from "../../test/checkinRegressionHarness";
import { deferred, rosterMatch } from "../../test/uiRegressionHarness";
import type { CheckinMatch } from "./api";

beforeEach(() => { lookupCheckin.mockReset(); });

describe("CheckinIdentityStep interaction lifetime", () => {
  it("external disabled blocks lookup and selection of existing matches", async () => {
    lookupCheckin.mockResolvedValue([rosterMatch, { ...rosterMatch, mid: 444 }]);
    const view = renderCheckin();
    fireEvent.change(screen.getByLabelText(/your name/i), { target: { value: "ada typed" } });
    view.changeContext("a", true);
    const input = screen.getByLabelText(/your name/i);
    expect(input).toBeDisabled();
    fireEvent.change(input, { target: { value: "blocked" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: "Find me" }));
    expect(input).toHaveValue("ada typed");
    expect(lookupCheckin).not.toHaveBeenCalled();
    view.changeContext("a");
    startLookup();
    await screen.findAllByRole("button", { name: "That's me" });
    view.changeContext("a", true);
    for (const button of screen.getAllByRole("button", { name: "That's me" })) {
      expect(button).toBeDisabled();
      fireEvent.click(button);
    }
    expect(nonNullConfirmations(view.onConfirm)).toEqual([]);
  });

  it("editing ambiguous results clears matches and confirmation; a canonical single match remains confirmable", async () => {
    lookupCheckin.mockResolvedValueOnce([
      rosterMatch, { ...rosterMatch, mid: 444, eligible: false, reason: "project", project_name: "" },
    ]).mockResolvedValueOnce([rosterMatch]);
    const view = renderCheckin();
    startLookup();
    const buttons = await screen.findAllByRole("button", { name: "That's me" });
    expect(buttons).toHaveLength(2);
    expect(buttons[0]).toBeEnabled();
    expect(buttons[1]).toBeDisabled();
    // Full result ambiguity includes ineligible namesakes.
    expect(nonNullConfirmations(view.onConfirm)).toEqual([]);
    fireEvent.click(buttons[0]);
    expect(view.onConfirm).toHaveBeenLastCalledWith(rosterMatch);
    fireEvent.change(screen.getByLabelText(/your name/i), { target: { value: "ada exact" } });
    expect(screen.queryByRole("button", { name: "That's me" })).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(view.onConfirm).toHaveBeenLastCalledWith(null);
    fireEvent.keyDown(screen.getByLabelText(/your name/i), { key: "Enter" });
    await waitFor(() => expect(view.onConfirm).toHaveBeenLastCalledWith(rosterMatch));
    expect(view.onConfirm.mock.lastCall?.[0]).toMatchObject({ name: "Ada Canonical", mid: 443 });
  });

  it.each(["empty", "error"] as const)("editing clears the previous %s lookup alert", async (result) => {
    if (result === "empty") lookupCheckin.mockResolvedValue([]);
    else lookupCheckin.mockRejectedValue(new Error("roster unavailable"));
    const view = renderCheckin();
    startLookup();
    await screen.findByRole("alert");
    await waitFor(() => expect(screen.getByLabelText(/your name/i)).toBeEnabled());
    fireEvent.change(screen.getByLabelText(/your name/i), { target: { value: "new spelling" } });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(view.onConfirm).toHaveBeenLastCalledWith(null);
    expect(nonNullConfirmations(view.onConfirm)).toEqual([]);
  });

  it.each(["success", "error"] as const)("disabled during lookup discards %s, settles the lock, and permits a fresh lookup", async (outcome) => {
    const pending = deferred<CheckinMatch[]>();
    lookupCheckin.mockReturnValueOnce(pending.promise).mockResolvedValueOnce([rosterMatch]);
    const view = renderCheckin();
    startLookup();
    await waitFor(() => expect(lookupCheckin).toHaveBeenCalledTimes(1));
    view.changeContext("a", true);
    await act(async () => {
      if (outcome === "success") pending.resolve([rosterMatch]);
      else pending.reject(new Error("disabled outage"));
    });
    await waitFor(() => expect(view.client.getMutationCache().getAll()[0].state.status).not.toBe("pending"));
    expect(screen.queryByText(rosterMatch.name)).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(nonNullConfirmations(view.onConfirm)).toEqual([]);
    view.changeContext("a");
    expect(screen.getByLabelText(/your name/i)).toBeEnabled();
    startLookup("fresh name");
    await waitFor(() => expect(view.onConfirm).toHaveBeenLastCalledWith(rosterMatch));
    expect(lookupCheckin).toHaveBeenLastCalledWith("a", "fresh name");
  });

  it("ignores a base onSuccess after unmount even though React Query completes the mutation", async () => {
    const pending = deferred<CheckinMatch[]>();
    lookupCheckin.mockReturnValue(pending.promise);
    const view = renderCheckin();
    startLookup();
    await waitFor(() => expect(lookupCheckin).toHaveBeenCalledTimes(1));
    view.unmount();
    await act(async () => pending.resolve([rosterMatch]));
    await waitFor(() => expect(view.client.getMutationCache().getAll()[0].state.status).toBe("success"));
    expect(nonNullConfirmations(view.onConfirm)).toEqual([]);
  });

  it("fresh StrictMode setup→cleanup→setup retains a usable mounted lifetime", async () => {
    lookupCheckin.mockResolvedValue([rosterMatch]);
    const view = renderCheckin(true);
    startLookup();
    await waitFor(() => expect(view.onConfirm).toHaveBeenLastCalledWith(rosterMatch));
    expect(lookupCheckin).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText(/your name/i)).toBeEnabled();
  });
});
