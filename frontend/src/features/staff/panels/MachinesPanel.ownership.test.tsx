import { fireEvent, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, expect, it } from "vitest";
import { MachinesPanel } from "./MachinesPanel";
import { serviceJob, serviceMachine, serviceRead, serviceType, setValue } from "../../../test/staffServiceOwnershipHarness";
import { cleanUploadSession, held, http, json, mountStaff, release, resetUploadSession, type HttpCall } from "../../../test/staffUploadHarness";

const types = [
  { ...serviceType("generic", 1), name: "Presses", capability_config: { metering_unit: "count" as const, requires_booking: false, uses_consumables: true } },
  { ...serviceType("generic", 3), name: "Cutters", capability_config: { metering_unit: "count" as const, requires_booking: false, uses_consumables: true } },
];
beforeEach(() => { resetUploadSession(); });
afterEach(() => { cleanUploadSession(); });
function RouterControls() {
  const navigate = useNavigate();
  return <><button onClick={() => navigate("/admin/machines/1-press/queue")}>Visit A directly</button><button onClick={() => navigate("/admin/machines/3-press/queue")}>Visit B directly</button></>;
}
function panel() {
  return <MemoryRouter initialEntries={["/admin/machines/1-press/queue"]}>
    <RouterControls />
    <MachinesPanel makerspaceId={1} canManage canConfigureMachineTypes={false} maintenanceEnabled={false}
      machineServiceEnabled printingEnabled reportsEnabled={false} delegatedRecipientRulesEnabled={false} />
  </MemoryRouter>;
}
function read(call: HttpCall) {
  if (call.path.endsWith("/machine-types")) return json(types);
  if (call.path.endsWith("/machines")) return json({ count: 2, next: null, previous: null, results: types.map((type, index) => serviceMachine(type, index + 11)) });
  if (call.path === "/auth/me") return json({ id: 1, is_superuser: false, makerspaces: [] });
  if (call.path.includes("/requests?")) {
    const id = new URLSearchParams(call.path.split("?")[1]).get("machine_type_id") === "1" ? 4 : 5;
    return json([serviceJob(id)]);
  }
  return serviceRead(call);
}

it("direct type A→B→A navigation preserves container service drafts and resets consumable fields and mutation error", async () => {
  const net = http((call) => call.method === "POST" && call.path.endsWith("consumable-pools") ? json({ detail: "A pool failed" }, 409) : read(call));
  mountStaff(panel());
  fireEvent.click(await screen.findByRole("button", { name: "Complete" }));
  setValue("Actual minutes", "37");
  setValue("Manual usage note", "A unfinished manual note");
  fireEvent.click(screen.getByRole("link", { name: "Machines & stock" }));
  setValue("Material", "A stock"); setValue("Brand", "A brand"); setValue("Initial quantity", "100");
  fireEvent.click(screen.getByRole("button", { name: "Add pool" }));
  await screen.findByText("A pool failed");
  expect(net.writes()[0].body).toMatchObject({ machine_type_id: 1, material: "A stock", unit: "count" });
  fireEvent.click(screen.getByRole("button", { name: "Visit B directly" }));
  await screen.findByText("Job B");
  expect(screen.queryByLabelText("Actual minutes")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("link", { name: "Machines & stock" }));
  expect(screen.getByLabelText("Material")).toHaveValue("");
  expect(screen.getByLabelText("Brand")).toHaveValue("");
  expect(screen.getByLabelText("Initial quantity")).toHaveValue(null);
  expect(screen.queryByText("A pool failed")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Actual minutes")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("link", { name: "Requests" }));
  expect(screen.getByLabelText("Manual usage note")).toHaveValue("");
  fireEvent.click(await screen.findByRole("button", { name: "Complete" }));
  setValue("Actual minutes", "51"); setValue("Manual usage note", "B unfinished note");
  fireEvent.click(screen.getByRole("link", { name: "Machines & stock" }));
  setValue("Material", "B stock"); setValue("Initial quantity", "200");
  fireEvent.click(screen.getByRole("button", { name: "Visit A directly" }));
  expect(await screen.findByLabelText("Actual minutes")).toHaveValue("37");
  expect(screen.getByLabelText("Manual usage note")).toHaveValue("A unfinished manual note");
  fireEvent.click(screen.getByRole("link", { name: "Machines & stock" }));
  expect(screen.getByLabelText("Material")).toHaveValue("");
  fireEvent.click(screen.getByRole("button", { name: "Visit B directly" }));
  expect(await screen.findByLabelText("Actual minutes")).toHaveValue("51");
  expect(screen.getByLabelText("Manual usage note")).toHaveValue("B unfinished note");
  fireEvent.click(screen.getByRole("link", { name: "Machines & stock" }));
  expect(screen.getByLabelText("Material")).toHaveValue("");
});

it("type-local pending state resets while old A settlement cannot clear B or erase preserved A drafts", async () => {
  const a = held<Response>(); const b = held<Response>();
  const net = http((call) => call.method === "POST" ? (call.path.includes("/4/") ? a.promise : b.promise) : read(call));
  mountStaff(panel());
  fireEvent.click(await screen.findByRole("button", { name: "Complete" }));
  setValue("Actual minutes", "37");
  fireEvent.click(screen.getByRole("button", { name: "Complete job" }));
  await waitFor(() => expect(net.writes()).toHaveLength(1));
  fireEvent.click(screen.getByRole("button", { name: "Visit B directly" }));
  fireEvent.click(await screen.findByRole("button", { name: "Complete" }));
  expect(screen.getByLabelText("Actual minutes")).toBeEnabled();
  setValue("Actual minutes", "51");
  fireEvent.click(screen.getByRole("button", { name: "Complete job" }));
  await waitFor(() => expect(net.writes()).toHaveLength(2));
  await release(a, json({ id: 4 }));
  expect(screen.getByLabelText("Actual minutes")).toHaveValue("51");
  expect(screen.getByLabelText("Actual minutes")).toBeDisabled();
  expect(screen.queryByText("Job completed")).not.toBeInTheDocument();
  await release(b, json({ id: 5 }));
  await waitFor(() => expect(screen.queryByLabelText("Actual minutes")).not.toBeInTheDocument());
  fireEvent.click(screen.getByRole("button", { name: "Visit A directly" }));
  expect(await screen.findByLabelText("Actual minutes")).toHaveValue("37");
});
