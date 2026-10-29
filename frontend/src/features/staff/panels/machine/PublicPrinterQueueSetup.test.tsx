import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PublicPrinterQueueSetup } from "./PublicPrinterQueueSetup";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../../../lib/api", () => ({ staffRequest }));
const path = "/admin/makerspaces/1/machine-service/printer-queue";
type QueueState = { enabled: boolean; queue_id: number | null; name: string | null };
const disabled: QueueState = { enabled: false, queue_id: null, name: null };
const enabled: QueueState = { enabled: true, queue_id: 9, name: "Public Requests" };

function renderSetup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><PublicPrinterQueueSetup makerspaceId={1} /></QueryClientProvider>);
  return client;
}

beforeEach(() => { staffRequest.mockReset(); });

describe("PublicPrinterQueueSetup", () => {
  it("waits for authoritative state, then enables a disabled-only queue with an empty POST", async () => {
    let resolveGet!: (value: typeof disabled) => void;
    let resolvePost!: (value: typeof enabled) => void;
    let state = disabled;
    let firstRead = true;
    staffRequest.mockImplementation((_path: string, options?: RequestInit) => {
      if (options?.method === "POST") return new Promise((resolve) => {
        resolvePost = (value) => { state = value; resolve(value); };
      });
      if (firstRead) {
        firstRead = false;
        return new Promise<QueueState>((resolve) => { resolveGet = resolve; });
      }
      return Promise.resolve(state);
    });
    const client = renderSetup();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    expect(screen.queryByRole("button", { name: "Enable public print requests" })).not.toBeInTheDocument();
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(path));
    resolveGet(disabled);
    fireEvent.click(await screen.findByRole("button", { name: "Enable public print requests" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(path, { method: "POST", body: "{}" }));
    expect(screen.getByRole("button")).toBeDisabled();
    resolvePost(enabled);
    expect(await screen.findByText(/Public print queue ready · Public Requests/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Enable public print requests" })).not.toBeInTheDocument();
    expect(client.getQueryData(["public-printer-queue-setup", 1])).toEqual(enabled);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["public-printer-queues"] });
  });

  it("displays refusal errors and allows retry without claiming the queue is enabled", async () => {
    staffRequest.mockImplementation((_path: string, options?: RequestInit) => options?.method === "POST"
      ? Promise.reject(new Error("Public Requests belongs to another machine type")) : Promise.resolve(disabled));
    renderSetup();
    fireEvent.click(await screen.findByRole("button", { name: "Enable public print requests" }));
    expect(await screen.findByText("Public Requests belongs to another machine type")).toBeVisible();
    expect(screen.getByRole("button", { name: "Enable public print requests" })).toBeEnabled();
    expect(screen.queryByText(/Public print queue ready ·/)).not.toBeInTheDocument();
  });

  it("shows GET errors with no setup action", async () => {
    staffRequest.mockRejectedValue(new Error("Printing is disabled"));
    renderSetup();
    expect(await screen.findByText("Printing is disabled")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Enable public print requests" })).not.toBeInTheDocument();
  });
});
