import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { publicV1Request, setAccessToken } = vi.hoisted(() => ({ publicV1Request: vi.fn(), setAccessToken: vi.fn() }));
vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, publicV1Request, setAccessToken };
});

import { MemberAuthPanel } from "./MemberAuthPanel";

function renderPanel(config: Record<string, unknown> = {}) {
  publicV1Request.mockImplementation((path: string) => (path === "/config" ? Promise.resolve(config) : Promise.resolve({})));
  return render(
    <MemoryRouter>
      <MemberAuthPanel onAuthenticated={vi.fn()} />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  publicV1Request.mockReset();
  setAccessToken.mockReset();
});

describe("member sign-in", () => {
  it("links to password recovery from the sign-in form", async () => {
    renderPanel();

    expect(screen.getByRole("heading", { level: 1, name: "Member sign in" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Forgot password?" })).toHaveAttribute("href", "/reset-password");
    await waitFor(() => expect(publicV1Request).toHaveBeenCalledWith("/config"));
  });

  it("drops the link while creating an account", async () => {
    renderPanel();
    await waitFor(() => expect(publicV1Request).toHaveBeenCalledWith("/config"));

    fireEvent.click(screen.getByRole("button", { name: "Create a member account" }));
    expect(screen.getByRole("heading", { level: 1, name: "Create a member account" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Forgot password?" })).not.toBeInTheDocument();
  });

  it("hides the link when password sign-in is switched off", async () => {
    renderPanel({ password_login: { enabled: false } });

    await waitFor(() => expect(screen.queryByRole("link", { name: "Forgot password?" })).not.toBeInTheDocument());
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
  });
});
