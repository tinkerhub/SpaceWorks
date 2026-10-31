import { accessToken } from "../../test/accessTokens";
import { StrictMode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../../components/ui";
import { getAccessToken, getSessionGeneration, setAccessToken } from "../../lib/apiSession";
import { changeEpoch, enter, epochChanges, held } from "../../test/authOwnership";
import { ChangePasswordForm, type ChangePasswordResponse } from "./ChangePasswordForm";

const request = vi.fn<(path: string, init: RequestInit) => Promise<ChangePasswordResponse>>();
const onChanged = vi.fn();
beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  setAccessToken(accessToken("account-A"));
  request.mockReset();
  onChanged.mockReset();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
});
afterEach(() => { vi.unstubAllGlobals(); });

function mount(strict = false) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  const form = (username: string) => {
    const content = <QueryClientProvider client={client}><ToastProvider>
      <ChangePasswordForm username={username} request={request} onChanged={onChanged} />
    </ToastProvider></QueryClientProvider>;
    return strict ? <StrictMode>{content}</StrictMode> : content;
  };
  const result = render(form("A"));
  return { ...result, visit: (username: string) => result.rerender(form(username)) };
}
function fillAndSubmit() {
  enter("Current password", "old-secret");
  enter("New password", "new-secret-123");
  enter("Confirm new password", "new-secret-123");
  fireEvent.submit(screen.getByLabelText("Current password").closest("form")!);
}
function noPublication() {
  expect(onChanged).not.toHaveBeenCalled();
  expect(screen.queryByText("Password updated")).not.toBeInTheDocument();
  expect(screen.queryByText("Password not updated")).not.toBeInTheDocument();
}

describe("password action ownership", () => {
  it.each(epochChanges)("CP01 ignores a parsed success after %s", async (kind) => {
    const response = held<ChangePasswordResponse>();
    request.mockReturnValue(response.promise);
    mount();
    fillAndSubmit();
    await waitFor(() => expect(request).toHaveBeenCalledTimes(1));
    await act(async () => {
      // The direct request already produced its parsed result; no API wrapper fence is involved.
      response.resolve({ detail: "ok", access: accessToken("obsolete") });
      await changeEpoch(kind);
    });
    noPublication();
    expect(getAccessToken()).toBe(kind === "new login" ? accessToken("account-B", { user_id: 2 }) : kind === "same-token login" ? accessToken("account-A") : "");
    expect(screen.getByLabelText("Current password")).toHaveValue("");
  });

  it("CP02 ignores success after unmount, including the base mutation callback", async () => {
    const response = held<ChangePasswordResponse>();
    request.mockReturnValue(response.promise);
    const view = mount();
    fillAndSubmit();
    await waitFor(() => expect(request).toHaveBeenCalledTimes(1));
    view.unmount();
    await act(async () => { response.resolve({ detail: "ok", access: accessToken("obsolete") }); });
    expect(getAccessToken()).toBe(accessToken("account-A"));
    expect(onChanged).not.toHaveBeenCalled();
  });

  it("CP03 A→B→A masks credentials immediately and rejects the old visit", async () => {
    const response = held<ChangePasswordResponse>();
    request.mockReturnValue(response.promise);
    const view = mount();
    fillAndSubmit();
    await waitFor(() => expect(request).toHaveBeenCalledTimes(1));
    view.visit("B");
    expect(screen.getByLabelText("Current password")).toHaveValue("");
    expect(screen.getByLabelText("New password")).toHaveValue("");
    view.visit("A");
    expect(screen.getByLabelText("Confirm new password")).toHaveValue("");
    await act(async () => { response.resolve({ detail: "ok", access: accessToken("obsolete") }); });
    expect(getAccessToken()).toBe(accessToken("account-A"));
    noPublication();
  });

  it("CP04 an external epoch render never exposes A's passwords under the fresh session", () => {
    const view = mount();
    enter("Current password", "A-secret");
    enter("New password", "A-new-secret");
    act(() => { setAccessToken(accessToken("account-B", { user_id: 2 })); });
    view.visit("A");
    for (const label of ["Current password", "New password", "Confirm new password"]) expect(screen.getByLabelText(label)).toHaveValue("");
  });

  it.each([false, true])("CP05 current rotation clears fields and advances exactly once (StrictMode=%s)", async (strict) => {
    request.mockResolvedValue({ detail: "ok", access: accessToken("rotated") });
    mount(strict);
    const epoch = getSessionGeneration();
    fillAndSubmit();
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    expect(getSessionGeneration()).toBe(epoch + 1);
    expect(getAccessToken()).toBe(accessToken("rotated"));
    expect(screen.getByRole("status")).toHaveTextContent("Password updated");
    for (const label of ["Current password", "New password", "Confirm new password"]) expect(screen.getByLabelText(label)).toHaveValue("");
    // A second current operation proves the intentional epoch advance did not wedge the owner.
    fillAndSubmit();
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(2));
    expect(request).toHaveBeenCalledTimes(2);
  });

  it("CP06 success without access keeps the token and generation and releases the form", async () => {
    request.mockResolvedValue({ detail: "ok" });
    mount();
    const epoch = getSessionGeneration();
    fillAndSubmit();
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    expect(getAccessToken()).toBe(accessToken("account-A"));
    expect(getSessionGeneration()).toBe(epoch);
    fillAndSubmit();
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(2));
  });

  it("CP07 repeated submit is deduplicated before a render commits", async () => {
    request.mockReturnValue(held<ChangePasswordResponse>().promise);
    mount();
    fillAndSubmit();
    const form = screen.getByLabelText("Current password").closest("form")!;
    act(() => { fireEvent.submit(form); fireEvent.submit(form); });
    await waitFor(() => expect(request).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("button", { name: "Updating…" })).toBeDisabled();
  });

  it("CP08 obsolete finally cannot unlock a newer pending visit", async () => {
    const old = held<ChangePasswordResponse>();
    const current = held<ChangePasswordResponse>();
    request.mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise);
    const view = mount();
    fillAndSubmit();
    await waitFor(() => expect(request).toHaveBeenCalledTimes(1));
    view.visit("B");
    fillAndSubmit();
    await waitFor(() => expect(request).toHaveBeenCalledTimes(2));
    await act(async () => { old.reject(new Error("obsolete error")); });
    expect(screen.getByRole("button", { name: "Updating…" })).toBeDisabled();
    expect(screen.queryByText("obsolete error")).not.toBeInTheDocument();
    noPublication();
    await act(async () => { current.resolve({ detail: "ok" }); });
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  });

  it("CP09 old-epoch error releases only its old pending tag and permits a fresh form", async () => {
    const old = held<ChangePasswordResponse>();
    request.mockReturnValueOnce(old.promise).mockResolvedValue({ detail: "ok" });
    mount();
    fillAndSubmit();
    await waitFor(() => expect(request).toHaveBeenCalledTimes(1));
    act(() => { setAccessToken(accessToken("account-B", { user_id: 2 })); });
    await act(async () => { old.reject(new Error("obsolete error")); });
    await waitFor(() => expect(screen.queryByRole("button", { name: "Updating…" })).not.toBeInTheDocument());
    expect(screen.getByLabelText("Current password")).toHaveValue("");
    expect(screen.queryByText("obsolete error")).not.toBeInTheDocument();
    noPublication();
    fillAndSubmit();
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  });

  it("CP10 a current error shows the real toast and allows a retry", async () => {
    request.mockRejectedValueOnce(new Error("current failure")).mockResolvedValue({ detail: "ok" });
    mount();
    fillAndSubmit();
    expect(await screen.findByText("Password not updated")).toBeInTheDocument();
    expect(screen.getByText("current failure")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Update password" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Update password" }));
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  });
});
