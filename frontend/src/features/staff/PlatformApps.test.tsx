import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, staffRequest };
});

import { StructuredApiError } from "../../lib/api";
import { ScannerPage } from "./PlatformApps";

function resolvePayload() {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ScannerPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.change(screen.getByLabelText("QR payload"), { target: { value: " SW:abc " } });
  fireEvent.click(screen.getByRole("button", { name: "Resolve" }));
}

beforeEach(() => {
  staffRequest.mockReset();
});

describe("ScannerPage", () => {
  it.each([403, 404])("reads a %s as an unrecognised code, not a permission error", async (status) => {
    staffRequest.mockRejectedValue(new StructuredApiError(status, { detail: "You do not have permission to perform this action." }));
    resolvePayload();

    expect(await screen.findByRole("alert")).toHaveTextContent("QR code not recognised on this site");
    expect(screen.queryByText(/permission/)).not.toBeInTheDocument();
    expect(staffRequest).toHaveBeenCalledWith("/admin/qr/resolve", { method: "POST", body: JSON.stringify({ payload: "SW:abc" }) });
  });

  it("shows the target and allowed actions of a resolved code", async () => {
    staffRequest.mockResolvedValue({ target: { type: "asset", asset_tag: "DRILL-1" }, allowed_actions: ["issue"] });
    resolvePayload();

    expect(await screen.findByText("issue")).toBeInTheDocument();
    expect(screen.getByText(/DRILL-1/)).toBeInTheDocument();
  });
});
