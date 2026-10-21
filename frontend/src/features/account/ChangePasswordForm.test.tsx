import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { setAccessToken } = vi.hoisted(() => ({ setAccessToken: vi.fn() }));
vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, setAccessToken };
});

import { ToastProvider } from "../../components/ui";
import { StructuredApiError } from "../../lib/api";
import { ChangePasswordForm, type ChangePasswordResponse } from "./ChangePasswordForm";

const request = vi.fn<(path: string, init: RequestInit) => Promise<ChangePasswordResponse>>();
const onChanged = vi.fn();

function renderForm({ withToasts = false } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const form = <ChangePasswordForm username="manager" request={request} onChanged={onChanged} />;
  return render(
    <QueryClientProvider client={client}>
      {withToasts ? <ToastProvider>{form}</ToastProvider> : form}
    </QueryClientProvider>,
  );
}

function fill(current: string, next: string, confirm: string) {
  fireEvent.change(screen.getByLabelText("Current password"), { target: { value: current } });
  fireEvent.change(screen.getByLabelText("New password"), { target: { value: next } });
  fireEvent.change(screen.getByLabelText("Confirm new password"), { target: { value: confirm } });
}

const submit = () => screen.getByRole("button", { name: "Update password" });

beforeEach(() => {
  request.mockReset();
  onChanged.mockReset();
  setAccessToken.mockReset();
});

describe("ChangePasswordForm", () => {
  it("keeps submit disabled while the confirmation is empty", () => {
    renderForm();
    fill("old-password", "new-password-123", "");
    expect(submit()).toBeDisabled();
    fireEvent.click(submit());
    expect(request).not.toHaveBeenCalled();
  });

  it("shows a mismatch message and blocks submit when confirmation differs", () => {
    renderForm();
    fill("old-password", "new-password-123", "new-password-124");
    expect(screen.getByRole("alert")).toHaveTextContent("Passwords do not match.");
    expect(submit()).toBeDisabled();
  });

  it("refuses a new password equal to the current one", () => {
    renderForm();
    fill("same-password", "same-password", "same-password");
    expect(screen.getByRole("alert")).toHaveTextContent("New password must be different.");
    expect(submit()).toBeDisabled();
  });

  it("stores the re-issued access token, reports success and clears the fields", async () => {
    request.mockResolvedValue({ detail: "Password updated.", access: "fresh-access" });
    renderForm();
    fill("old-password", "new-password-123", "new-password-123");
    fireEvent.click(submit());

    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    expect(request).toHaveBeenCalledWith("/auth/change-password", {
      method: "POST",
      credentials: "include",
      body: JSON.stringify({ current_password: "old-password", new_password: "new-password-123" }),
    });
    expect(setAccessToken).toHaveBeenCalledWith("fresh-access");
    expect(screen.getByLabelText("Current password")).toHaveValue("");
    expect(screen.getByLabelText("Confirm new password")).toHaveValue("");
  });

  it("does not touch the access token when the server re-issues none", async () => {
    request.mockResolvedValue({ detail: "Password updated." });
    renderForm();
    fill("old-password", "new-password-123", "new-password-123");
    fireEvent.click(submit());
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(setAccessToken).not.toHaveBeenCalled();
  });

  it("renders field errors from the response body next to each field", async () => {
    request.mockRejectedValue(new StructuredApiError(400, {
      current_password: "Current password is incorrect.",
      new_password: ["This password is too short.", "This password is too common."],
    }));
    renderForm();
    fill("wrong-password", "short", "short");
    fireEvent.click(submit());

    const alerts = await screen.findAllByRole("alert");
    expect(alerts.map((alert) => alert.textContent)).toEqual([
      "Current password is incorrect.",
      "This password is too short. This password is too common.",
    ]);
    expect(onChanged).not.toHaveBeenCalled();
  });

  it("explains throttling instead of echoing the raw 429", async () => {
    request.mockRejectedValue(new StructuredApiError(429, { detail: "Request was throttled." }));
    renderForm();
    fill("old-password", "new-password-123", "new-password-123");
    fireEvent.click(submit());
    expect(await screen.findByRole("alert")).toHaveTextContent("Too many attempts. Wait a minute and try again.");
  });

  it("confirms the change in a toast", async () => {
    request.mockResolvedValue({ detail: "Password updated." });
    renderForm({ withToasts: true });
    fill("old-password", "new-password-123", "new-password-123");
    fireEvent.click(submit());
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Password updated"));
  });

  it("offers the emailed recovery flow when the account has no password yet", async () => {
    const message = "This account has no password yet. Use “Forgot password” on the sign-in page to set one.";
    request.mockRejectedValue(new StructuredApiError(400, { current_password: [message] }));
    renderForm();
    fill("anything", "new-password-123", "new-password-123");
    fireEvent.click(submit());

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.getByLabelText("Current password")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("link", { name: "Set a password by email" })).toHaveAttribute("href", "/reset-password");
  });

  it("lets each password be shown and hidden", () => {
    renderForm();
    const current = screen.getByLabelText("Current password");
    expect(current).toHaveAttribute("type", "password");
    fireEvent.click(screen.getAllByRole("button", { name: "Show password" })[0]);
    expect(current).toHaveAttribute("type", "text");
  });
});
