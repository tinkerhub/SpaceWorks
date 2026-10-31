import { accessToken } from "../../test/accessTokens";
import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { publicV1Request, staffRequest } = vi.hoisted(() => ({ publicV1Request: vi.fn(), staffRequest: vi.fn() }));
vi.mock("../../lib/api", async () => ({
  ...await vi.importActual<typeof import("../../lib/api")>("../../lib/api"), publicV1Request, staffRequest,
}));
import { getAccessToken, getSessionGeneration, setAccessToken } from "../../lib/apiSession";
import { changeEpoch, epochChanges, held } from "../../test/authOwnership";
import { chooseSignup, mountMember, submitMember } from "../../test/memberOwnershipHarness";

const loginResult = { access: accessToken("member-current"), surface: "member", user: { username: "A" } };
let operation: ReturnType<typeof held<typeof loginResult>>;
const loginCalls = () => publicV1Request.mock.calls.filter(([path]) => path === "/auth/login");
beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  setAccessToken(accessToken("account-A"));
  operation = held<typeof loginResult>();
  publicV1Request.mockReset();
  staffRequest.mockReset();
  publicV1Request.mockImplementation((path: string) => path === "/config" ? Promise.resolve({}) : operation.promise);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
});
afterEach(() => { vi.unstubAllGlobals(); });

describe("member password and signup ownership", () => {
  it.each(epochChanges)("MA01 parsed login cannot publish after %s", async (kind) => {
    const view = mountMember();
    submitMember();
    expect(loginCalls()).toHaveLength(1);
    await act(async () => { operation.resolve(loginResult); await changeEpoch(kind); });
    expect(view.authenticated).not.toHaveBeenCalled();
    expect(getAccessToken()).toBe(kind === "new login" ? accessToken("account-B", { user_id: 2 }) : kind === "same-token login" ? accessToken("account-A") : "");
    expect(screen.queryByText(/Unable to continue/)).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toHaveValue("");
    expect(screen.getByLabelText("Email")).toBeEnabled();
  });

  it("MA02 unmounted login cannot install or call its parent", async () => {
    const view = mountMember();
    submitMember();
    view.unmount();
    await act(async () => { operation.resolve(loginResult); });
    expect(getAccessToken()).toBe(accessToken("account-A"));
    expect(view.authenticated).not.toHaveBeenCalled();
  });

  it("MA03 slug A→B→A clears credentials immediately and rejects A's old login", async () => {
    const view = mountMember();
    submitMember();
    view.visit("B");
    expect(screen.getByLabelText("Email")).toHaveValue("");
    expect(screen.getByLabelText("Password")).toHaveValue("");
    view.visit("A");
    await act(async () => { operation.resolve(loginResult); });
    expect(getAccessToken()).toBe(accessToken("account-A"));
    expect(view.authenticated).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();
  });

  it("MA04 current login installs once, clears its secret and leaves a usable form", async () => {
    const view = mountMember();
    const generation = getSessionGeneration();
    submitMember();
    expect(loginCalls()[0][1]).toEqual({ method: "POST", credentials: "include", body: JSON.stringify({
      username: "a@example.test", password: "private-password", surface: "member",
    }) });
    await act(async () => { operation.resolve(loginResult); });
    expect(view.authenticated).toHaveBeenCalledTimes(1);
    expect(getAccessToken()).toBe(accessToken("member-current"));
    expect(getSessionGeneration()).toBe(generation + 1);
    expect(screen.getByLabelText("Password")).toHaveValue("");
    expect(screen.getByLabelText("Email")).toBeEnabled();
    expect(screen.getByRole("button", { name: "Create a member account" })).toBeEnabled();
  });

  it("MA05 repeated Enter deduplicates and freezes inputs and mode during login", async () => {
    mountMember();
    submitMember();
    const form = screen.getByRole("form", { name: "Member sign in" });
    act(() => { fireEvent.submit(form); fireEvent.submit(form); });
    expect(loginCalls()).toHaveLength(1);
    expect(screen.getByLabelText("Email")).toBeDisabled();
    expect(screen.getByLabelText("Password")).toBeDisabled();
    const mode = screen.getByRole("button", { name: "Create a member account" });
    expect(mode).toBeDisabled();
    fireEvent.click(mode);
    expect(screen.getByRole("heading", { name: "Member sign in" })).toBeInTheDocument();
  });

  it("MA06 Back cancels the old login and its finally cannot unlock a new submission", async () => {
    const old = operation;
    const current = held<typeof loginResult>();
    const view = mountMember();
    submitMember();
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(view.cancel).toHaveBeenCalledTimes(1);
    publicV1Request.mockImplementation((path: string) => path === "/config" ? Promise.resolve({}) : current.promise);
    submitMember();
    await act(async () => { old.reject(new Error("old login failed")); });
    expect(screen.getByLabelText("Email")).toBeDisabled();
    expect(screen.queryByText("old login failed")).not.toBeInTheDocument();
    expect(view.authenticated).not.toHaveBeenCalled();
    await act(async () => { current.resolve(loginResult); });
    expect(view.authenticated).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("Email")).toBeEnabled();
  });

  it("MA07 signup succeeds with a notice and returns to login without installing access", async () => {
    const view = mountMember();
    chooseSignup();
    submitMember(true);
    expect(publicV1Request).toHaveBeenCalledWith("/auth/member-sign-up", { method: "POST", body: JSON.stringify({
      display_name: "Member A", email: "a@example.test", phone: "", password: "private-password", website: "",
    }) });
    await act(async () => { operation.resolve(loginResult); });
    expect(screen.getByRole("heading", { name: "Member sign in" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Check your email to verify the new account");
    expect(screen.getByLabelText("Password")).toHaveValue("");
    expect(getAccessToken()).toBe(accessToken("account-A"));
    expect(view.authenticated).not.toHaveBeenCalled();
  });

  it.each(["Back", "slug", "epoch", "unmount"])("MA08 signup notice and error cannot survive %s", async (cancel) => {
    const view = mountMember();
    chooseSignup();
    submitMember(true);
    if (cancel === "Back") {
      fireEvent.click(screen.getByRole("button", { name: "Back" }));
      fireEvent.click(screen.getByRole("button", { name: "Back to sign in" }));
    } else if (cancel === "slug") { view.visit("B"); view.visit("A"); }
    else if (cancel === "epoch") { act(() => { setAccessToken(accessToken("account-B", { user_id: 2 })); }); }
    else view.unmount();
    await act(async () => { operation.resolve(loginResult); });
    expect(screen.queryByText(/Check your email to verify/)).not.toBeInTheDocument();
    expect(view.authenticated).not.toHaveBeenCalled();
    expect(getAccessToken()).toBe(cancel === "epoch" ? accessToken("account-B", { user_id: 2 }) : accessToken("account-A"));
  });

  it("MA09 a current rejected login releases pending and presents its error", async () => {
    mountMember();
    submitMember();
    await act(async () => { operation.reject(new Error("Wrong password")); });
    expect(screen.getByRole("alert")).toHaveTextContent("Wrong password");
    expect(screen.getByLabelText("Password")).toBeEnabled();
    expect(getAccessToken()).toBe(accessToken("account-A"));
  });

  it.each(["login", "signup"])("MA11 old-epoch %s failure releases only the old tag without showing its error", async (mode) => {
    const view = mountMember();
    if (mode === "signup") chooseSignup();
    submitMember(mode === "signup");
    act(() => { setAccessToken(accessToken("account-B", { user_id: 2 })); });
    await act(async () => { operation.reject(new Error("obsolete account failure")); });
    expect(screen.queryByText("obsolete account failure")).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Member sign in" })).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toHaveValue("");
    expect(screen.getByLabelText("Password")).toBeEnabled();
    expect(view.authenticated).not.toHaveBeenCalled();
    expect(getAccessToken()).toBe(accessToken("account-B", { user_id: 2 }));
  });

  it("MA10 a pending signup freezes its mode and duplicate submits", () => {
    mountMember();
    chooseSignup();
    submitMember(true);
    fireEvent.submit(screen.getByRole("form", { name: "Create a member account" }));
    expect(publicV1Request.mock.calls.filter(([path]) => path === "/auth/member-sign-up")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Back to sign in" })).toBeDisabled();
    expect(screen.getByLabelText("Name")).toBeDisabled();
  });
});
