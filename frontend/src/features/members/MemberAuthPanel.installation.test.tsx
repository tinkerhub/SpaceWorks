import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ComponentProps } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type ProviderProps = ComponentProps<typeof import("../auth/SocialSignInButtons").SocialSignInButtons>;
const installation = vi.hoisted(() => ({ blocked: true }));
const delivery = vi.hoisted(() => ({
  result: null as Parameters<ProviderProps["onSuccess"]>[0] | null,
  before: false, after: true, providerErrors: [] as unknown[],
}));
vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  const { SessionInstallError } = await import("../../lib/sessionIntent");
  return { ...actual, setAccessToken: (token: string) => {
    if (installation.blocked) throw new SessionInstallError("storage_unavailable");
    actual.setAccessToken(token);
  } };
});
// The external provider completion is the only replaced leaf. In particular, its
// catch cannot display an error once the real parent begins a new host intent.
vi.mock("../auth/SocialSignInButtons", () => ({
  SocialSignInButtons: (props: ProviderProps) => <button type="button" disabled={props.disabled} onClick={() => {
    const current = props.isHostCurrent!;
    delivery.before = current();
    if (!delivery.before) return;
    try { props.onSuccess(delivery.result!); }
    catch (error) { if (current()) delivery.providerErrors.push(error); }
    delivery.after = current();
  }}>Complete provider sign-in</button>,
}));

import { clearAccessToken, getAccessToken, getSessionGeneration, setAccessToken } from "../../lib/apiSession";
import { SessionInstallError } from "../../lib/sessionIntent";
import { accessToken } from "../../test/accessTokens";
import { enter, held } from "../../test/authOwnership";
import { MemberAuthPanel } from "./MemberAuthPanel";

const oldToken = () => accessToken("existing-member");
const providerToken = () => accessToken("provider-member");
let client: QueryClient;
let passwordReply: ReturnType<typeof held<Response>>;
const loginCalls: RequestInit[] = [];
beforeEach(() => {
  localStorage.clear(); sessionStorage.clear(); clearAccessToken();
  setAccessToken(oldToken());
  installation.blocked = true;
  delivery.result = { access: providerToken(), user: { username: "provider-member" }, outcome: "existing" };
  delivery.before = false; delivery.after = true; delivery.providerErrors.length = 0;
  passwordReply = held<Response>(); loginCalls.length = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const path = new URL(String(input), "http://localhost").pathname;
    if (path.endsWith("/config")) return new Response("{}", { headers: { "Content-Type": "application/json" } });
    if (path.endsWith("/auth/login")) { loginCalls.push(init); return passwordReply.promise; }
    throw new Error(`Unexpected request: ${path}`);
  }));
});
afterEach(() => { client?.clear(); vi.unstubAllGlobals(); });

function mount() {
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const authenticated = vi.fn();
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/m/kochi/member"]}>
    <MemberAuthPanel makerspaceSlug="kochi" onAuthenticated={authenticated} />
  </MemoryRouter></QueryClientProvider>);
  enter("Email", "member@example.test"); enter("Password", "private-secret");
  return authenticated;
}
function completeProvider() { fireEvent.click(screen.getByRole("button", { name: "Complete provider sign-in" })); }
function expectFailure() {
  expect(screen.getByRole("alert")).toHaveTextContent(new SessionInstallError("storage_unavailable").message);
  expect(screen.getByLabelText("Password")).toHaveValue("");
  expect(screen.getByLabelText("Password")).toBeEnabled();
  expect(screen.getByRole("button", { name: "Create a member account" })).toBeEnabled();
}

describe("member provider session completion", () => {
  it("owns the installation error after begin invalidates the provider's host intent", () => {
    const authenticated = mount();
    const epoch = getSessionGeneration();
    completeProvider();
    expect(delivery.before).toBe(true);
    expect(delivery.after).toBe(false);
    expect(delivery.providerErrors).toEqual([]);
    expectFailure();
    expect(authenticated).not.toHaveBeenCalled();
    expect(getAccessToken()).toBe(oldToken());
    expect(getSessionGeneration()).toBe(epoch);
  });

  it("a current provider retry after repair installs and calls the parent exactly once", () => {
    const authenticated = mount();
    const epoch = getSessionGeneration();
    completeProvider(); expectFailure();
    installation.blocked = false;
    completeProvider();
    expect(authenticated).toHaveBeenCalledTimes(1);
    expect(getAccessToken()).toBe(providerToken());
    expect(getSessionGeneration()).toBe(epoch + 1);
    expect(screen.getByLabelText("Password")).toHaveValue("");
    expect(loginCalls).toHaveLength(0);
  });

  it("releases the failed social action for a real password retry and keeps that retry pending until transport completes", async () => {
    const authenticated = mount();
    completeProvider(); expectFailure();
    installation.blocked = false;
    enter("Password", "reentered-secret");
    const form = screen.getByRole("form", { name: "Member sign in" });
    act(() => { fireEvent.submit(form); fireEvent.submit(form); });
    await waitFor(() => expect(loginCalls).toHaveLength(1));
    expect(screen.getByLabelText("Password")).toBeDisabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(authenticated).not.toHaveBeenCalled();
    const epoch = getSessionGeneration();
    const access = accessToken("password-retry-member");
    await act(async () => { passwordReply.resolve(new Response(JSON.stringify({ access, surface: "member", user: { username: "member" } }), {
      headers: { "Content-Type": "application/json" },
    })); });
    await waitFor(() => expect(authenticated).toHaveBeenCalledTimes(1));
    expect(JSON.parse(String(loginCalls[0].body))).toEqual({ username: "member@example.test", password: "reentered-secret", surface: "member" });
    expect(getAccessToken()).toBe(access);
    expect(getSessionGeneration()).toBe(epoch + 1);
    expect(screen.getByLabelText("Password")).toHaveValue("");
    expect(screen.getByLabelText("Email")).toBeEnabled();
  });
});
