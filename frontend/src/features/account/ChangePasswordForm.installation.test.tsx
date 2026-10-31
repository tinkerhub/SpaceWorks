import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const installation = vi.hoisted(() => ({ blocked: false }));
vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  const { SessionInstallError } = await import("../../lib/sessionIntent");
  return { ...actual, setAccessToken: (token: string) => {
    if (installation.blocked) throw new SessionInstallError("storage_unavailable");
    actual.setAccessToken(token);
  } };
});

import { ToastProvider } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { clearAccessToken, getAccessToken, getSessionGeneration, setAccessToken } from "../../lib/apiSession";
import { accessToken } from "../../test/accessTokens";
import { enter } from "../../test/authOwnership";
import { ChangePasswordForm, type ChangePasswordResponse } from "./ChangePasswordForm";

const original = () => accessToken("password-member");
const rotated = () => accessToken("password-member", { auth_generation: "22222222-2222-4222-8222-222222222222" });
const calls: RequestInit[] = [];
let client: QueryClient;

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  clearAccessToken();
  setAccessToken(original());
  calls.length = 0;
  installation.blocked = true;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const path = new URL(String(input), "http://localhost").pathname;
    if (!path.endsWith("/auth/change-password")) throw new Error(`Unexpected request: ${path}`);
    calls.push(init);
    return new Response(JSON.stringify({ detail: "Password updated.", access: rotated() }), {
      status: 200, headers: { "Content-Type": "application/json" },
    });
  }));
});
afterEach(() => { client?.clear(); vi.unstubAllGlobals(); });

function mount() {
  client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  const changed = vi.fn();
  render(<QueryClientProvider client={client}><MemoryRouter><ToastProvider>
    <ChangePasswordForm username="member" request={(path, init) => staffRequest<ChangePasswordResponse>(path, init)} onChanged={changed} />
  </ToastProvider></MemoryRouter></QueryClientProvider>);
  return changed;
}
function submit(current = "old-secret", next = "new-secret-123") {
  enter("Current password", current);
  enter("New password", next);
  enter("Confirm new password", next);
  fireEvent.submit(screen.getByLabelText("Current password").closest("form")!);
}
function emptyPasswords() {
  for (const label of ["Current password", "New password", "Confirm new password"]) {
    expect(screen.getByLabelText(label)).toHaveValue("");
  }
}

describe("password rotation installation", () => {
  it("reports the completed server change truthfully, clears every secret and publishes no failed installation", async () => {
    const changed = mount();
    const epoch = getSessionGeneration();
    submit();
    const message = await screen.findByText("Password updated; sign in again.");
    expect(message.closest('[role="alert"]')).not.toBeNull();
    emptyPasswords();
    expect(changed).not.toHaveBeenCalled();
    expect(getAccessToken()).toBe(original());
    expect(getSessionGeneration()).toBe(epoch);
    expect(screen.queryByText("Password not updated")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    expect(document.querySelector('[role="alert"][aria-live="assertive"]')).toBeEmptyDOMElement();
    expect(screen.getByRole("button", { name: "Update password" })).toBeDisabled();
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({ method: "POST", credentials: "include" });
    expect(JSON.parse(String(calls[0].body))).toEqual({ current_password: "old-secret", new_password: "new-secret-123" });
  });

  it("releases the failed action so a fresh submission after storage repair installs once and completes", async () => {
    const changed = mount();
    const epoch = getSessionGeneration();
    submit();
    await screen.findByText("Password updated; sign in again.");
    installation.blocked = false;
    // The server already changed the password: the next request uses that new password.
    submit("new-secret-123", "newer-secret-456");
    await waitFor(() => expect(changed).toHaveBeenCalledTimes(1));
    expect(calls).toHaveLength(2);
    expect(JSON.parse(String(calls[1].body))).toEqual({ current_password: "new-secret-123", new_password: "newer-secret-456" });
    expect(getAccessToken()).toBe(rotated());
    expect(getSessionGeneration()).toBe(epoch + 1);
    emptyPasswords();
    expect(screen.getByRole("status")).toHaveTextContent("Password updated");
    expect(screen.getByRole("alert")).toBeEmptyDOMElement();
    expect(screen.queryByText("Password not updated")).not.toBeInTheDocument();
  });
});
