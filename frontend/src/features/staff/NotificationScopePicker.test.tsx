import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, staffRequest };
});

import { useScopeOptions } from "./NotificationScopePicker";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  staffRequest.mockReset();
  staffRequest.mockResolvedValue([{ id: 1, name: "Thing" }]);
});

describe("useScopeOptions", () => {
  it("never asks the machine endpoints while the machines module is off", async () => {
    const { result } = renderHook(() => useScopeOptions(7, true, false), { wrapper });

    await waitFor(() => expect(result.current.categories).toHaveLength(1));
    expect(result.current.machineTypes).toEqual([]);
    expect(result.current.machines).toEqual([]);
    expect(staffRequest.mock.calls.map(([path]) => path)).toEqual(["/admin/makerspace/7/categories"]);
  });

  it("offers machine scopes with the module on", async () => {
    const { result } = renderHook(() => useScopeOptions(7), { wrapper });

    await waitFor(() => expect(result.current.machines).toHaveLength(1));
    expect(result.current.machineTypes).toHaveLength(1);
  });
});
