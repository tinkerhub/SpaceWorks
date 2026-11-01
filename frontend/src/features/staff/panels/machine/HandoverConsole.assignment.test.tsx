import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it } from "vitest";
import { serviceJob, serviceRead } from "../../../../test/staffServiceOwnershipHarness";
import { cleanUploadSession, http, json, mountStaff, resetUploadSession } from "../../../../test/staffUploadHarness";
import { HandoverConsole } from "./HandoverConsole";

beforeEach(() => resetUploadSession());
afterEach(() => cleanUploadSession());

it("shows actual assignments before legacy bucket names for pooled and legacy jobs, retaining payment and handover controls", async () => {
  const base = { ...serviceJob(), status: "completed", completed_at: null };
  const assigned = { id: 12, name: "Actual laser", status: "idle" };
  const bucket = { id: 11, name: "Legacy printer bucket", status: "idle" };
  const rows = [
    { ...base, title: "Reassigned job", machine: bucket, assigned_machine: assigned,
      payment: { id: 71, status: "pending", amount: "15.00", currency: "usd" } },
    { ...base, id: 5, title: "Pooled job", machine: null, assigned_machine: assigned },
    { ...base, id: 6, title: "Legacy job", machine: bucket, assigned_machine: null },
  ];
  const net = http((call) => call.path.includes("/requests?") ? json(rows) : serviceRead(call));
  mountStaff(<HandoverConsole makerspaceId={1} enabled />);
  const reassigned = (await screen.findByText("Reassigned job")).closest("tr")!;
  const pooled = screen.getByText("Pooled job").closest("tr")!;
  const legacy = screen.getByText("Legacy job").closest("tr")!;
  expect(within(reassigned).getByText("Maker · Actual laser")).toBeVisible();
  expect(within(reassigned).queryByText(/Legacy printer bucket/)).not.toBeInTheDocument();
  expect(within(pooled).getByText("Maker · Actual laser")).toBeVisible();
  expect(within(legacy).getByText("Maker · Legacy printer bucket")).toBeVisible();
  expect(within(reassigned).getByRole("button", { name: "Record payment · $15.00" })).toBeVisible();
  expect(within(reassigned).getByRole("button", { name: "Hand over" })).toBeVisible();
  expect(within(pooled).queryByRole("button", { name: /Record payment/ })).not.toBeInTheDocument();
  fireEvent.click(within(pooled).getByRole("button", { name: "Hand over" }));
  await waitFor(() => expect(net.writes()).toHaveLength(1));
  expect(net.writes()[0]).toMatchObject({ method: "POST", path: "/admin/machine-service/requests/5/collect", body: {} });
});
