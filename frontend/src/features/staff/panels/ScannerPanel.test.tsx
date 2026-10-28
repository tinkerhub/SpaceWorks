import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../../lib/api")>("../../../lib/api");
  return { ...actual, staffRequest };
});

import { StructuredApiError } from "../../../lib/api";
import { ScannerPanel } from "./ScannerPanel";
import type { Makerspace } from "./shared";

const makerspace = { id: 7, name: "Lab", public_code: "lab", slug: "lab" } as Makerspace;

function renderPanel() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>
      <ScannerPanel makerspace={makerspace} isSuperadmin={false} makerspaces={[makerspace]} />
    </QueryClientProvider>,
  );
}

async function resolveWith(status: number) {
  staffRequest.mockImplementation(async (path: string) => {
    if (path === "/admin/qr/resolve") throw new StructuredApiError(status, { detail: "You do not have permission to perform this action." });
    if (path === "/auth/me") return { makerspaces: [] };
    return { results: [] };
  });
  renderPanel();
  fireEvent.change(screen.getByLabelText("QR payload"), { target: { value: "SW:abc123" } });
  fireEvent.click(screen.getByRole("button", { name: "Resolve" }));
}

beforeEach(() => {
  staffRequest.mockReset();
});

describe("ScannerPanel QR resolve errors", () => {
  it("shows a tenant-origin 403 as an unrecognised code, not a permission error", async () => {
    await resolveWith(403);

    expect(await screen.findByText("QR code not recognised on this site.")).toBeVisible();
    expect(screen.queryByText(/permission/i)).not.toBeInTheDocument();
  });

  it("says the same for a 404", async () => {
    await resolveWith(404);

    expect(await screen.findByText("QR code not recognised on this site.")).toBeVisible();
  });
});

describe("ScannerPanel revoke", () => {
  it("shows the revoked QR from the revoke response instead of re-resolving", async () => {
    const qr = { id: 5, makerspace: 7, payload: "SW:abc123", status: "active" };
    staffRequest.mockImplementation(async (path: string) => {
      if (path === "/admin/qr/resolve") return { qr, target: { type: "box", id: 3, label: "Bin", code: "BX-1" }, allowed_actions: ["revoke"] };
      if (path === "/admin/qr/5/revoke") return { ...qr, status: "revoked" };
      if (path === "/auth/me") return { makerspaces: [] };
      return { results: [] };
    });
    renderPanel();
    fireEvent.change(screen.getByLabelText("QR payload"), { target: { value: "SW:abc123" } });
    fireEvent.click(screen.getByRole("button", { name: "Resolve" }));
    fireEvent.click(await screen.findByRole("button", { name: "Revoke QR…" }));
    fireEvent.click(await screen.findByRole("button", { name: "Revoke QR" }));

    expect(await screen.findByText("Revoked")).toBeVisible();
    expect(screen.queryByText("Active")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Revoke QR…" })).not.toBeInTheDocument();
    expect(staffRequest.mock.calls.filter(([path]) => path === "/admin/qr/resolve")).toHaveLength(1);
  });
});
