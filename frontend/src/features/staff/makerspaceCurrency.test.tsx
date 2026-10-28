import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useMakerspaceCurrency } from "./paymentsApi";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../lib/api", () => ({ staffRequest }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useMakerspaceCurrency", () => {
  beforeEach(() => {
    staffRequest.mockReset();
  });

  it("reads the currency off the auth payload, without asking for payment settings", async () => {
    staffRequest.mockImplementation(async (path: string) => {
      if (path === "/auth/me") return { makerspaces: [{ id: 3, currency: "inr" }, { id: 7, currency: "usd" }] };
      throw new Error(`unexpected ${path}`);
    });

    const { result } = renderHook(() => useMakerspaceCurrency(7), { wrapper });

    await waitFor(() => expect(result.current).toBe("USD"));
    expect(staffRequest.mock.calls.map(([path]) => path)).toEqual(["/auth/me"]);
  });

  it("falls back to the payment settings for a makerspace the actor is not a member of", async () => {
    staffRequest.mockImplementation(async (path: string) => {
      if (path === "/auth/me") return { is_superuser: true, makerspaces: [] };
      if (path === "/admin/makerspace/7/payment-settings") return { default_currency: "eur" };
      throw new Error(`unexpected ${path}`);
    });

    const { result } = renderHook(() => useMakerspaceCurrency(7), { wrapper });

    await waitFor(() => expect(result.current).toBe("EUR"));
  });
});
