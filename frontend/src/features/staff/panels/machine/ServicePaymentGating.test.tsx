import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MachineServiceRequest } from "../../../../generated/api";
import { HandoverConsole } from "./HandoverConsole";
import { ServiceQueue } from "./ServiceQueue";
import { blankServiceDraft } from "./serviceDrafts";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../../../lib/api")>("../../../../lib/api");
  return { ...actual, staffRequest };
});

const job = {
  id: 4, title: "Rover wheel hub", status: "completed", payment: null, payment_status: "none", payment_amount: null,
  requester_name: "Asha Menon", completed_at: "2026-10-22T04:00:00Z",
} as unknown as MachineServiceRequest;

function withModules(modules: string[]) {
  staffRequest.mockImplementation(async (path: string) => {
    if (path === "/admin/makerspaces") return [{ id: 7, name: "Lab", slug: "lab", enabled_modules: modules }];
    if (path.includes("machine-service/requests")) return [job];
    return [];
  });
}

function wrap(node: ReactNode) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{node}</QueryClientProvider>);
}

function queue() {
  return wrap(
    <ServiceQueue makerspaceId={7} requests={[job]} loading={false} draft={blankServiceDraft()} setDraft={() => {}}
      machines={[]} pools={[]} meta={() => "meta"} pending={false} onSubmit={() => {}} machineNoun="Printer" unitLabel="grams" hasPool />,
  );
}

beforeEach(() => {
  staffRequest.mockReset();
});

describe("machine service payment copy", () => {
  it("shows no payment chip or column when the payments module is off", async () => {
    withModules(["machines", "machine_service"]);
    queue();
    wrap(<HandoverConsole makerspaceId={7} enabled />);

    expect(await screen.findByText("Finished jobs waiting at the desk, ready to hand over.")).toBeVisible();
    expect(await screen.findByRole("button", { name: "Hand over" })).toBeVisible();
    expect(screen.queryByText(/^Payment /)).toBeNull();
    expect(screen.queryByRole("columnheader", { name: "Payment" })).toBeNull();
  });

  it("keeps the payment state when the payments module is on", async () => {
    withModules(["machines", "machine_service", "payments"]);
    queue();

    expect(await screen.findByText("Payment free")).toBeVisible();
  });

  it("still shows a real charge even with the module off", async () => {
    withModules(["machines", "machine_service"]);
    const owed = { ...job, payment: { id: 1, amount: "40.00", currency: "inr", status: "pending" } } as unknown as MachineServiceRequest;
    wrap(
      <ServiceQueue makerspaceId={7} requests={[owed]} loading={false} draft={blankServiceDraft()} setDraft={() => {}}
        machines={[]} pools={[]} meta={() => "meta"} pending={false} onSubmit={() => {}} machineNoun="Printer" unitLabel="grams" hasPool />,
    );

    expect(await screen.findByText("Payment owed INR 40.00")).toBeVisible();
  });
});
