import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getSessionGeneration } from "../../lib/apiSession";
import {
  enterRecovery, fillRecoveryPassword, heldRecovery, mountRecoveryRoutes,
  RECOVERY_PASSWORD, settleRecovery, submitRecovery,
} from "../../test/recoveryOwnershipHarness";

const { publicV1Request } = vi.hoisted(() => ({ publicV1Request: vi.fn() }));
vi.mock("../../lib/api", () => ({ publicV1Request }));

const EMAIL_A = "alice@example.test";
const EMAIL_B = "bob@example.test";
const requestButton = () => screen.getByRole("button", { name: "Request recovery code" });
const request = () => submitRecovery("Reset password");
const enterEmail = (email: string) => enterRecovery("Email", email);
const payload = (index: number) => JSON.parse(publicV1Request.mock.calls[index][1].body);

function expectFreshRequest(email: string) {
  expect(screen.getByRole("heading", { name: "Reset password" })).toBeInTheDocument();
  expect(screen.getByLabelText("Email")).toHaveValue(email);
  expect(requestButton()).toBeEnabled();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Request another code/ })).not.toBeInTheDocument();
}

beforeEach(() => { publicV1Request.mockReset(); });
afterEach(() => vi.useRealTimers());

describe("email-owned recovery", () => {
  it.each(["resolve", "reject"] as const)(
    "keeps B pending through obsolete A's %s/finally, then confirms exactly B's request",
    async (outcome) => {
      vi.useFakeTimers();
      const epoch = getSessionGeneration();
      const oldA = heldRecovery();
      const currentB = heldRecovery();
      const confirmation = heldRecovery();
      publicV1Request.mockReturnValueOnce(oldA.promise).mockReturnValueOnce(currentB.promise)
        .mockReturnValueOnce(confirmation.promise);
      mountRecoveryRoutes({ recovery: "/reset-password" });
      enterEmail(EMAIL_A); request();
      expect(requestButton()).toHaveAttribute("aria-busy", "true");
      expect(screen.getByLabelText("Email")).toBeEnabled();

      enterEmail(EMAIL_B);
      expectFreshRequest(EMAIL_B);
      request();
      expect(payload(0)).toEqual({ email: EMAIL_A });
      expect(payload(1)).toEqual({ email: EMAIL_B });
      await settleRecovery(oldA, outcome, "Obsolete A acknowledgement");
      expect(screen.queryByText("Obsolete A acknowledgement")).not.toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(screen.queryByLabelText("Six-digit code")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Request another code/ })).not.toBeInTheDocument();
      expect(requestButton()).toBeDisabled();
      expect(requestButton()).toHaveAttribute("aria-busy", "true");
      request();
      expect(publicV1Request).toHaveBeenCalledTimes(2);

      // A's settlement must neither begin B's cooldown nor clear B's pending owner.
      act(() => vi.advanceTimersByTime(5000));
      await settleRecovery(currentB, "resolve", "B acknowledgement");
      expect(screen.getByText("B acknowledgement")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Request another code in 60s" })).toBeDisabled();
      enterRecovery("Six-digit code", "123456");
      fillRecoveryPassword();
      submitRecovery("Enter your recovery code");
      expect(publicV1Request).toHaveBeenNthCalledWith(3, "/auth/reset-password", {
        method: "POST", body: JSON.stringify({ email: EMAIL_B, code: "123456", new_password: RECOVERY_PASSWORD }),
      });
      await settleRecovery(confirmation, "resolve");
      expect(screen.getByRole("heading", { name: "Password updated" })).toBeInTheDocument();
      expect(getSessionGeneration()).toBe(epoch);
    },
  );

  it.each(["resolve", "reject"] as const)(
    "does not reactivate the first A email visit after A → B → A and an obsolete %s",
    async (outcome) => {
      const epoch = getSessionGeneration();
      const oldA = heldRecovery();
      const freshA = heldRecovery();
      publicV1Request.mockReturnValueOnce(oldA.promise).mockReturnValueOnce(freshA.promise);
      mountRecoveryRoutes({ recovery: "/reset-password" });
      enterEmail(EMAIL_A); request();
      enterEmail(EMAIL_B);
      expectFreshRequest(EMAIL_B);
      enterEmail(EMAIL_A);
      expectFreshRequest(EMAIL_A);
      request();
      await settleRecovery(oldA, outcome, "First A acknowledgement");
      expect(screen.queryByText("First A acknowledgement")).not.toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(screen.queryByLabelText("Six-digit code")).not.toBeInTheDocument();
      expect(requestButton()).toHaveAttribute("aria-busy", "true");
      expect(requestButton()).toBeDisabled();
      request();
      expect(publicV1Request).toHaveBeenCalledTimes(2);
      await settleRecovery(freshA, "resolve", "Fresh A acknowledgement");
      expect(screen.getByText("Fresh A acknowledgement")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Request another code in 60s" })).toBeDisabled();
      expect(getSessionGeneration()).toBe(epoch);
    },
  );

  it("cannot publish an unmounted request's completion into a newly mounted recovery form", async () => {
    const old = heldRecovery();
    publicV1Request.mockReturnValueOnce(old.promise);
    const view = mountRecoveryRoutes({ recovery: "/reset-password" });
    enterEmail(EMAIL_A); request();
    view.unmount();
    mountRecoveryRoutes({ recovery: "/reset-password" });
    enterEmail(EMAIL_B);
    await settleRecovery(old, "resolve", "Unmounted acknowledgement");
    expectFreshRequest(EMAIL_B);
    expect(screen.queryByText("Unmounted acknowledgement")).not.toBeInTheDocument();
    expect(publicV1Request).toHaveBeenCalledTimes(1);
  });

  it("deduplicates request and confirmation submits before React commits their pending state", async () => {
    const requestResult = heldRecovery();
    const confirmResult = heldRecovery();
    publicV1Request.mockReturnValueOnce(requestResult.promise).mockReturnValueOnce(confirmResult.promise);
    mountRecoveryRoutes({ recovery: "/reset-password" });
    enterEmail(EMAIL_B);
    const requestForm = screen.getByRole("form", { name: "Reset password" });
    act(() => { fireEvent.submit(requestForm); fireEvent.submit(requestForm); });
    expect(publicV1Request).toHaveBeenCalledTimes(1);
    expect(payload(0)).toEqual({ email: EMAIL_B });
    await settleRecovery(requestResult, "resolve");
    enterRecovery("Six-digit code", "654321"); fillRecoveryPassword();
    const confirmForm = screen.getByRole("form", { name: "Enter your recovery code" });
    act(() => { fireEvent.submit(confirmForm); fireEvent.submit(confirmForm); });
    expect(publicV1Request).toHaveBeenCalledTimes(2);
    expect(payload(1)).toEqual({ email: EMAIL_B, code: "654321", new_password: RECOVERY_PASSWORD });
    await settleRecovery(confirmResult, "resolve");
    expect(screen.getByRole("heading", { name: "Password updated" })).toBeInTheDocument();
  });
});
