import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MachineType } from "../../machinesApi";
import { MachineServiceConsole } from "./MachineServiceConsole";
import { blankServiceDraft } from "./serviceDrafts";
import { isolateMachineTestSession, machineConsoleTestClient, machineTestMakerspaces } from "./machineConsoleTestUtils";

isolateMachineTestSession();

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../../../lib/api", async (importOriginal) => ({
  ...await importOriginal<typeof import("../../../../lib/api")>(),
  staffRequest,
}));

const machineType: MachineType = {
  id: 7, slug: "laser", name: "Laser cutters", icon: "", is_builtin: false, managing_action: "", makerspace: 1,
  capability_config: { metering_unit: "minutes", requires_booking: false },
};

function Console() {
  const [draft, setDraft] = useState(blankServiceDraft);
  return <MachineServiceConsole makerspaceId={1} canManage machineType={machineType} machines={[]} pools={[]} draft={draft} setDraft={setDraft} />;
}

beforeEach(() => {
  staffRequest.mockReset();
  staffRequest.mockImplementation(async (path?: string) => {
    if (path === "/admin/makerspaces") return machineTestMakerspaces();
    if (path?.includes("machine-service/requests?")) return [{
      id: 4, title: "Paid laser job", status: "completed", payment_status: "none", payment_amount: null,
      payment: { id: 41, status: "pending", amount: "14.50", currency: "usd" },
    }];
    return [];
  });
});

describe("MachineServiceConsole cache refresh", () => {
  it("refreshes the Operations reports and every payment view after recording a payment", async () => {
    const client = machineConsoleTestClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    render(<QueryClientProvider client={client}><Console /></QueryClientProvider>);

    const job = (await screen.findByText("Paid laser job")).closest("article")!;
    fireEvent.click(within(job).getByRole("button", { name: /Record payment/ }));
    const confirm = await screen.findAllByRole("button", { name: "Record payment" });
    fireEvent.click(confirm[confirm.length - 1]);

    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/machine-service/requests/4/record-manual-payment", expect.objectContaining({ method: "POST" }),
    ));
    await waitFor(() => {
      const keys = invalidate.mock.calls.map(([filters]) => JSON.stringify(filters?.queryKey));
      expect(keys).toEqual(expect.arrayContaining([
        JSON.stringify(["machine-service-report", 1]),
        JSON.stringify(["printer-service-report", 1]),
        JSON.stringify(["payments", 1]),
      ]));
    });
  });
});
