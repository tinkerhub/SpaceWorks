import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getSessionGeneration } from "../../lib/apiSession";
import {
  fillRecoveryPassword, heldRecovery, mountRecoveryRoutes, RECOVERY_PASSWORD,
  recoverySnapshot, settleRecovery, submitRecovery,
} from "../../test/recoveryOwnershipHarness";
import { LegacyPasswordResetForm } from "./LegacyPasswordResetForm";
import { CONFIRM_FAILURE_MESSAGE } from "./passwordRecovery";

const { publicV1Request } = vi.hoisted(() => ({ publicV1Request: vi.fn() }));
// Only the transport leaf is replaced; the component, recovery API and owner hook are real.
vi.mock("../../lib/api", () => ({ publicV1Request }));

const A = "/reset-password?uid=user-A&token=token-A";
const B = "/reset-password?uid=user-B&token=token-A";
const pristine = { secrets: ["", ""], updated: false, error: null };
const updateButton = () => screen.getByRole("button", { name: "Update password" });
const submit = () => submitRecovery("Set a new password");

function directForm(uid: string, token: string) {
  return <MemoryRouter useTransitions={false}>
    <LegacyPasswordResetForm uid={uid} token={token} />
  </MemoryRouter>;
}

beforeEach(() => { publicV1Request.mockReset(); });

describe("legacy reset ownership", () => {
  it.each([
    ["uid only", B],
    ["token only", "/reset-password?uid=user-A&token=token-B"],
  ])("clears secrets and a current error before paint when %s changes on the same path", async (_name, next) => {
    const commits: ReturnType<typeof recoverySnapshot>[] = [];
    publicV1Request.mockRejectedValueOnce(new Error("Current rejection"));
    const view = mountRecoveryRoutes({ A, B: next }, () => commits.push(recoverySnapshot()));
    fillRecoveryPassword();
    await act(async () => submit());
    expect(screen.getByRole("alert")).toHaveTextContent(CONFIRM_FAILURE_MESSAGE);
    expect(screen.getByLabelText("New password")).toHaveValue(RECOVERY_PASSWORD);

    view.visit("B");
    expect(commits[commits.length - 1]).toEqual(pristine);
    expect(recoverySnapshot()).toEqual(pristine);
    expect(updateButton()).toBeDisabled();
  });

  it.each([
    ["uid only", B],
    ["token only", "/reset-password?uid=user-A&token=token-B"],
  ])("clears completed success before paint when %s changes", async (_name, next) => {
    const commits: ReturnType<typeof recoverySnapshot>[] = [];
    publicV1Request.mockResolvedValueOnce({ detail: "Password updated." });
    const view = mountRecoveryRoutes({ A, B: next },
      () => commits.push(recoverySnapshot()));
    fillRecoveryPassword();
    await act(async () => submit());
    expect(screen.getByRole("heading", { name: "Password updated" })).toBeInTheDocument();
    view.visit("B");
    expect(commits[commits.length - 1]).toEqual(pristine);
  });

  it.each([
    ["B", "resolve"], ["B", "reject"], ["fresh A", "resolve"], ["fresh A", "reject"],
  ] as const)("keeps %s pending when obsolete A settles with %s", async (destination, outcome) => {
    const epoch = getSessionGeneration();
    const oldA = heldRecovery();
    const current = heldRecovery();
    publicV1Request.mockReturnValueOnce(oldA.promise).mockReturnValueOnce(current.promise);
    const view = mountRecoveryRoutes({ A, B });
    fillRecoveryPassword(); submit();
    view.visit("B");
    if (destination === "fresh A") view.visit("A");
    expect(recoverySnapshot()).toEqual(pristine);
    fillRecoveryPassword(); submit();
    await settleRecovery(oldA, outcome);

    expect(screen.queryByRole("heading", { name: "Password updated" })).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(updateButton()).toBeDisabled();
    expect(updateButton()).toHaveAttribute("aria-busy", "true");
    submit();
    expect(publicV1Request).toHaveBeenCalledTimes(2);
    expect(JSON.parse(publicV1Request.mock.calls[1][1].body)).toEqual({
      uid: destination === "B" ? "user-B" : "user-A", token: "token-A", new_password: RECOVERY_PASSWORD,
    });
    expect(getSessionGeneration()).toBe(epoch);
    await settleRecovery(current, "resolve");
    expect(screen.getByRole("heading", { name: "Password updated" })).toBeInTheDocument();
  });

  it("resets a directly rerendered form's context without replacing its input instance", async () => {
    publicV1Request.mockRejectedValueOnce(new Error("Current error"))
      .mockResolvedValueOnce({ detail: "Password updated." });
    const view = render(directForm("user-A", "token-A"));
    const input = screen.getByLabelText("New password");
    fillRecoveryPassword();
    await act(async () => submit());
    expect(screen.getByRole("alert")).toHaveTextContent(CONFIRM_FAILURE_MESSAGE);
    view.rerender(directForm("user-B", "token-A"));
    expect(screen.getByLabelText("New password")).toBe(input);
    expect(recoverySnapshot()).toEqual(pristine);
    fillRecoveryPassword();
    await act(async () => submit());
    expect(screen.getByRole("heading", { name: "Password updated" })).toBeInTheDocument();
    view.rerender(directForm("user-B", "token-B"));
    expect(recoverySnapshot()).toEqual(pristine);
  });

  it("does not revive the first A action on direct A → B → A prop changes", async () => {
    const oldA = heldRecovery();
    const freshA = heldRecovery();
    publicV1Request.mockReturnValueOnce(oldA.promise).mockReturnValueOnce(freshA.promise);
    const view = render(directForm("user-A", "token-A"));
    fillRecoveryPassword(); submit();
    view.rerender(directForm("user-B", "token-A"));
    expect(recoverySnapshot()).toEqual(pristine);
    view.rerender(directForm("user-A", "token-A"));
    expect(recoverySnapshot()).toEqual(pristine);
    fillRecoveryPassword(); submit();
    await settleRecovery(oldA, "resolve");
    expect(screen.queryByRole("heading", { name: "Password updated" })).not.toBeInTheDocument();
    expect(updateButton()).toHaveAttribute("aria-busy", "true");
    await settleRecovery(freshA, "resolve");
    expect(screen.getByRole("heading", { name: "Password updated" })).toBeInTheDocument();
  });

  it("deduplicates two synchronous submit events and preserves the current legacy happy path", async () => {
    const current = heldRecovery();
    publicV1Request.mockReturnValueOnce(current.promise);
    mountRecoveryRoutes({ A });
    fillRecoveryPassword();
    const form = screen.getByRole("form", { name: "Set a new password" });
    act(() => { fireEvent.submit(form); fireEvent.submit(form); });
    expect(publicV1Request).toHaveBeenCalledExactlyOnceWith("/auth/reset-password", {
      method: "POST", body: JSON.stringify({ uid: "user-A", token: "token-A", new_password: RECOVERY_PASSWORD }),
    });
    await settleRecovery(current, "resolve");
    expect(screen.getByRole("heading", { name: "Password updated" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to sign in" })).toHaveAttribute("href", "/admin");
  });
});
