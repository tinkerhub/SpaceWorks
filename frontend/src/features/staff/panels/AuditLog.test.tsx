import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../../lib/api")>("../../../lib/api");
  return { ...actual, staffRequest };
});

import { AuditLog } from "./AuditLog";

function renderLog(makerspaceId?: number) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AuditLog makerspaceId={makerspaceId} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  staffRequest.mockReset();
  staffRequest.mockResolvedValue({ count: 0, next: null, previous: null, results: [] });
});

describe("AuditLog", () => {
  it("scopes the list to the active makerspace, which an origin-locked site requires", async () => {
    renderLog(7);
    await waitFor(() => expect(staffRequest).toHaveBeenCalled());
    expect(String(staffRequest.mock.calls[0][0])).toContain("makerspace=7");
    expect(screen.getByText(/Every state change in this makerspace/)).toBeInTheDocument();
  });

  it("does not claim a single makerspace when it is not scoped to one", async () => {
    renderLog();
    await waitFor(() => expect(staffRequest).toHaveBeenCalled());
    expect(String(staffRequest.mock.calls[0][0])).not.toContain("makerspace=");
    expect(screen.queryByText(/in this makerspace/)).not.toBeInTheDocument();
  });
});
