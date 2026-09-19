import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { HandoverConsole } from "./HandoverConsole";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../../../lib/api", () => ({ staffRequest }));

describe("HandoverConsole", () => {
  beforeEach(() => {
    staffRequest.mockReset();
    staffRequest.mockImplementation(async (_path: string, options?: RequestInit) => {
      if (options?.method === "POST") return {};
      return [
        {
          id: 17,
          title: "Laser cutting",
          requester_name: "Ada",
          status: "completed",
          completed_at: null,
          machine: null,
          payment: { id: 71, status: "pending", amount: "15.00", currency: "usd" },
          payment_status: "none",
          payment_amount: null,
        },
        {
          id: 18,
          title: "Free repair",
          requester_name: "Lin",
          status: "completed",
          completed_at: null,
          machine: null,
          payment: null,
          payment_status: "none",
          payment_amount: null,
        },
      ];
    });
  });

  it("lets collect-only staff settle a manual debt before handover", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <HandoverConsole makerspaceId={3} enabled />
      </QueryClientProvider>,
    );

    const payableRow = (await screen.findByText("Laser cutting")).closest("li")!;
    const freeRow = screen.getByText("Free repair").closest("li")!;
    expect(within(payableRow).getByText(/payment owed USD 15.00/i)).toBeVisible();
    expect(within(payableRow).getByRole("button", { name: /record payment/i })).toBeVisible();
    expect(within(freeRow).queryByRole("button", { name: /record payment/i })).not.toBeInTheDocument();
    expect(within(freeRow).getByRole("button", { name: "Hand over" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /record payment.*USD 15.00/i }));

    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/machine-service/requests/17/record-manual-payment",
      { method: "POST", body: "{}" },
    ));
  });
});
