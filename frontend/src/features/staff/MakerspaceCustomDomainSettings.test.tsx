import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, staffRequest: vi.fn() };
});

import { MakerspaceCustomDomainSettings } from "./MakerspaceCustomDomainSettings";
import type { Makerspace } from "./panels/shared";

const base: Makerspace = {
  id: 7, name: "Forge", public_code: "forge", slug: "forge", telegram_group_chat_id: "",
  frontend_domain: "forge.example.org", hidden_from_central_directory: false,
};

function renderDomain(isSuperadmin: boolean, platformHosting?: boolean) {
  const makerspace = { ...base, platform_hosting: platformHosting };
  const client = new QueryClient();
  render(
    <QueryClientProvider client={client}>
      <MakerspaceCustomDomainSettings makerspace={makerspace} settings={makerspace} loading={false} isSuperadmin={isSuperadmin} />
    </QueryClientProvider>,
  );
  return screen.getByLabelText("Domain");
}

describe("custom domain form", () => {
  it("is read-only for a non-superadmin on a self-hosted instance", () => {
    expect(renderDomain(false, false)).toHaveAttribute("readonly");
    expect(screen.getByText("Only a superadmin can change the custom domain on this instance.")).toBeInTheDocument();
  });

  it("treats unknown hosting as self-hosted", () => {
    expect(renderDomain(false, undefined)).toHaveAttribute("readonly");
  });

  it("stays editable for a superadmin", () => {
    expect(renderDomain(true, false)).not.toHaveAttribute("readonly");
  });

  it("stays editable for a space manager on managed hosting", () => {
    expect(renderDomain(false, true)).not.toHaveAttribute("readonly");
  });
});
