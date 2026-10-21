import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { publicV1Request } = vi.hoisted(() => ({ publicV1Request: vi.fn() }));
vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, publicV1Request };
});

import { LoginPanel } from "../../features/staff/LoginPanel";
import { AuthLayout } from "./AuthLayout";

beforeEach(() => {
  publicV1Request.mockReset();
  publicV1Request.mockResolvedValue({ email_enabled: true });
});

describe("AuthLayout", () => {
  it("puts the title, description and form in the main landmark beside a decorative brand panel", () => {
    render(
      <MemoryRouter>
        <AuthLayout kicker="Security" title="Set a new password" description="Choose something only you know.">
          <form aria-label="Example"><button type="submit">Save</button></form>
        </AuthLayout>
      </MemoryRouter>,
    );

    const main = screen.getByRole("main");
    expect(main).toHaveAttribute("id", "main-content");
    expect(screen.getByRole("heading", { level: 1, name: "Set a new password" })).toBeInTheDocument();
    expect(screen.getByText("Choose something only you know.")).toBeInTheDocument();
    expect(screen.getByRole("form", { name: "Example" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Skip to main content" })).toBeInTheDocument();
    // The brand panel is decoration only: no landmark, nothing announced.
    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
  });

  it("renders the staff sign-in form with its existing behaviour", async () => {
    const onSubmit = vi.fn();
    render(
      <MemoryRouter>
        <LoginPanel guestOnly={false} isPending={false} error="Invalid credentials." onSubmit={onSubmit} />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { level: 1, name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByText("Space Manager desk")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Invalid credentials.");
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "manager" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "secret-pass" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(onSubmit).toHaveBeenCalledWith({ username: "manager", password: "secret-pass" });
    expect(await screen.findByRole("link", { name: "Forgot password?" })).toHaveAttribute("href", "/reset-password");
    await waitFor(() => expect(publicV1Request).toHaveBeenCalledWith("/config"));
  });
});
