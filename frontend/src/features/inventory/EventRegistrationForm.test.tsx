import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { getAccessToken, refreshAccessToken } = vi.hoisted(() => ({
  getAccessToken: vi.fn(),
  refreshAccessToken: vi.fn(),
}));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, getAccessToken, refreshAccessToken };
});

import { EventRegistrationForm } from "./EventRegistrationForm";

function renderForm() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <EventRegistrationForm
          makerspaceSlug="forge"
          signInHref="/m/forge/member"
          publicToken="evt-1"
          waitlist={false}
          approvalRequired={false}
          customForm={[]}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("event registration session", () => {
  beforeEach(() => {
    getAccessToken.mockReturnValue("");
    refreshAccessToken.mockReset();
  });

  it("restores a reloaded member's session and shows the form", async () => {
    refreshAccessToken.mockResolvedValue(true);
    renderForm();

    expect(await screen.findByRole("button", { name: "Register" })).toBeInTheDocument();
    expect(refreshAccessToken).toHaveBeenCalled();
  });

  it("offers sign-in before the form when nobody is signed in", async () => {
    refreshAccessToken.mockResolvedValue(false);
    renderForm();

    expect(await screen.findByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/m/forge/member");
    expect(screen.queryByRole("button", { name: "Register" })).not.toBeInTheDocument();
  });
});
