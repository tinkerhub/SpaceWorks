import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, staffRequest: vi.fn() };
});

import { MakerspacePublicStatsSettings } from "./MakerspacePublicStatsSettings";
import type { Makerspace } from "./panels/shared";

function renderCard(modules: string[]) {
  const makerspace = { id: 7, name: "Forge", public_code: "forge", slug: "forge", enabled_modules: modules } as Makerspace;
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <MakerspacePublicStatsSettings makerspace={makerspace} loading={false} />
    </QueryClientProvider>,
  );
}

describe("MakerspacePublicStatsSettings copy", () => {
  it("promises no print hours without printing and names the masked borrower as the page does", () => {
    renderCard(["public_inventory"]);
    expect(screen.getByText("A public activity page with popular hardware and current loans.")).toBeVisible();
    expect(screen.getByText(/every borrower is shown as “Borrower”/)).toBeVisible();
    expect(screen.queryByText(/“Member”/)).toBeNull();
  });

  it("mentions print hours with printing on", () => {
    renderCard(["public_inventory", "printing"]);
    expect(screen.getByText("A public activity page with print hours, popular hardware and current loans.")).toBeVisible();
  });
});
