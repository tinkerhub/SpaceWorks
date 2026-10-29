import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MachineType } from "../../machinesApi";
import { PrinterServiceConsole } from "./PrinterServiceConsole";
import { testMachine } from "./machineTestFixtures";
import { blankServiceDraft } from "./serviceDrafts";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../../../lib/api", () => ({ staffRequest }));

beforeEach(() => {
  staffRequest.mockReset();
  staffRequest.mockImplementation(async (path: string) => {
    if (path.endsWith("/printer-queue")) return { enabled: false, queue_id: null, name: null };
    if (path.includes("machine-service-report")) return { printer_metrics: [] };
    return [];
  });
});

function renderConsole(flag: boolean | undefined, canManage = true, printingEnabled = true) {
  // The access-list field is optional on the server; nested/older types omit it.
  const type: MachineType & { can_manage_public_queue?: boolean } = {
    ...testMachine.machine_type, ...(flag === undefined ? {} : { can_manage_public_queue: flag }),
  };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}>
    <PrinterServiceConsole makerspaceId={1} machineType={type} canManage={canManage}
      printingEnabled={printingEnabled} machines={[]} pools={[]} draft={blankServiceDraft()} setDraft={vi.fn()} />
  </QueryClientProvider>);
}

describe("Printer public queue authority", () => {
  it("offers setup only when the server explicitly grants queue management", async () => {
    renderConsole(true);
    expect(await screen.findByRole("button", { name: "Enable public print requests" })).toBeEnabled();
    expect(staffRequest.mock.calls.some(([path]) => String(path).endsWith("/printer-queue"))).toBe(true);
  });

  it.each([undefined, false])("does not infer setup authority from general management (flag=%s)", async (flag) => {
    renderConsole(flag);
    await waitFor(() => expect(staffRequest).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: "Enable public print requests" })).not.toBeInTheDocument();
    expect(staffRequest.mock.calls.some(([path]) => String(path).endsWith("/printer-queue"))).toBe(false);
  });

  it.each([[false, true], [true, false]])("gates setup when console management=%s, printing=%s", async (manage, printing) => {
    renderConsole(true, manage, printing);
    await waitFor(() => expect(screen.queryByRole("button", { name: "Enable public print requests" })).not.toBeInTheDocument());
    expect(staffRequest.mock.calls.some(([path]) => String(path).endsWith("/printer-queue"))).toBe(false);
  });
});
