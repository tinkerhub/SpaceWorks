import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const installation = vi.hoisted(() => ({ blockedToken: "" }));
vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  const { SessionInstallError } = await import("../../lib/sessionIntent");
  return { ...actual, setAccessToken: (token: string) => {
    if (token === installation.blockedToken) throw new SessionInstallError("storage_unavailable");
    actual.setAccessToken(token);
  } };
});

import { clearAccessToken, getAccessToken, getSessionGeneration, setAccessToken } from "../../lib/apiSession";
import { SessionInstallError } from "../../lib/sessionIntent";
import { accessToken } from "../../test/accessTokens";
import { enter } from "../../test/authOwnership";
import { invitationMember, invitationRedeemed } from "../../test/organizationOwnershipHarness";
import { OrganizationInvitationRedeemPage } from "./OrganizationInvitationRedeemPage";

const memberToken = () => accessToken("invitation-member");
const staffToken = () => accessToken("invitation-member", { surface: "staff", staff_scope: "platform" });
const calls: { path: string; init: RequestInit }[] = [];
const commits: string[] = [];
let client: QueryClient;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json" },
});
beforeEach(() => {
  localStorage.clear(); sessionStorage.clear(); clearAccessToken();
  setAccessToken(accessToken("pre-invitation-member"));
  installation.blockedToken = "";
  calls.length = 0; commits.length = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const path = new URL(String(input), "http://localhost").pathname.replace(/^\/api\/v1/, "");
    calls.push({ path, init });
    if (path === "/auth/refresh") return json({}, 401);
    if (path === "/auth/login") {
      const surface = JSON.parse(String(init.body)).surface;
      return json({ access: surface === "staff" ? staffToken() : memberToken(), surface, user: invitationMember });
    }
    if (path === "/auth/organization-invitations/redeem/") return json(invitationRedeemed);
    throw new Error(`Unexpected invitation request: ${path}`);
  }));
});
afterEach(() => { vi.restoreAllMocks(); client?.clear(); vi.unstubAllGlobals(); });

function LocationProbe() {
  const location = useLocation();
  useEffect(() => { commits.push(location.pathname); }, [location.key]);
  return <output aria-label="Invitation route">{location.pathname}</output>;
}
function mount() {
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  client.setQueryData(["private"], { owner: "member", secret: "preserved" });
  const clear = vi.spyOn(client, "clear");
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/invitations/A"]}>
    <LocationProbe /><Routes>
      <Route path="/invitations/:token" element={<OrganizationInvitationRedeemPage />} />
      <Route path="/admin" element={<h1>Staff destination</h1>} />
    </Routes>
  </MemoryRouter></QueryClientProvider>);
  return clear;
}
async function submitMember() {
  await screen.findByLabelText("Username or email");
  enter("Username or email", "typed@example.test");
  enter("Password", "member-secret");
  fireEvent.submit(screen.getByLabelText("Password").closest("form")!);
}
function submitStaff() {
  enter("Password", "staff-secret");
  fireEvent.submit(screen.getByLabelText("Password").closest("form")!);
}
const loginCalls = () => calls.filter(({ path }) => path === "/auth/login");
const redemptions = () => calls.filter(({ path }) => path.endsWith("/redeem/"));

describe("invitation session installation", () => {
  it("preserves one durable redemption and the member session on staff installation failure, then clears cache and navigates once on retry", async () => {
    const clear = mount();
    await submitMember();
    await screen.findByRole("heading", { name: "Staff sign-in" });
    expect(redemptions()).toHaveLength(1);
    expect(new Headers(redemptions()[0].init.headers).get("Authorization")).toBe(`Bearer ${memberToken()}`);
    expect(screen.getByLabelText("Username or email")).toHaveValue(invitationMember.username);
    const epoch = getSessionGeneration();
    installation.blockedToken = staffToken();
    submitStaff();
    expect(await screen.findByRole("alert")).toHaveTextContent(new SessionInstallError("storage_unavailable").message);
    expect(screen.getByRole("heading", { name: "Invitation redeemed" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Staff sign-in" })).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toHaveValue("");
    expect(screen.getByLabelText("Username or email")).toHaveValue(invitationMember.username);
    expect(getAccessToken()).toBe(memberToken());
    expect(getSessionGeneration()).toBe(epoch);
    expect(client.getQueryData(["private"])).toEqual({ owner: "member", secret: "preserved" });
    expect(clear).not.toHaveBeenCalled();
    expect(commits).toEqual(["/invitations/A"]);
    expect(redemptions()).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Sign in to staff console" })).toBeEnabled();

    installation.blockedToken = "";
    submitStaff();
    await screen.findByRole("heading", { name: "Staff destination" });
    expect(getAccessToken()).toBe(staffToken());
    expect(getSessionGeneration()).toBe(epoch + 1);
    expect(clear).toHaveBeenCalledTimes(1);
    expect(client.getQueryData(["private"])).toBeUndefined();
    expect(commits.filter((path) => path === "/admin")).toHaveLength(1);
    expect(redemptions()).toHaveLength(1);
    expect(loginCalls().map(({ init }) => JSON.parse(String(init.body)).surface)).toEqual(["member", "staff", "staff"]);
  });

  it("clears an initial member secret without automatic redemption when installation fails and allows a current member retry", async () => {
    installation.blockedToken = memberToken();
    const clear = mount();
    const original = getAccessToken();
    const epoch = getSessionGeneration();
    await submitMember();
    expect(await screen.findByRole("alert")).toHaveTextContent(new SessionInstallError("storage_unavailable").message);
    expect(screen.getByLabelText("Password")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Sign in and continue" })).toBeEnabled();
    expect(getAccessToken()).toBe(original);
    expect(getSessionGeneration()).toBe(epoch);
    expect(redemptions()).toHaveLength(0);
    expect(clear).not.toHaveBeenCalled();
    expect(screen.queryByText("Invitation redeemed")).not.toBeInTheDocument();
    installation.blockedToken = "";
    await submitMember();
    await screen.findByRole("heading", { name: "Staff sign-in" });
    await waitFor(() => expect(redemptions()).toHaveLength(1));
    expect(getAccessToken()).toBe(memberToken());
    expect(getSessionGeneration()).toBe(epoch + 1);
    expect(loginCalls()).toHaveLength(2);
    expect(JSON.parse(String(redemptions()[0].init.body))).toEqual({ token: "A" });
    expect(clear).not.toHaveBeenCalled();
    expect(client.getQueryData(["private"])).toEqual({ owner: "member", secret: "preserved" });
    expect(commits).toEqual(["/invitations/A"]);
    expect(screen.getByLabelText("Password")).toHaveValue("");
  });
});
