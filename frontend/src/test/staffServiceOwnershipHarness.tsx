import { useEffect, useState } from "react";
import type { MachineServiceRequest, PrinterPool } from "../generated/api";
import { fireEvent, screen } from "@testing-library/react";
import type { Machine, MachineType } from "../features/staff/machinesApi";
import { MachineServiceConsole } from "../features/staff/panels/machine/MachineServiceConsole";
import { PrinterServiceConsole } from "../features/staff/panels/machine/PrinterServiceConsole";
import { blankServiceDraft, type ServiceDraft } from "../features/staff/panels/machine/serviceDrafts";
import { machineTestMakerspaces } from "../features/staff/panels/machine/machineConsoleTestUtils";
import { json, type HttpCall } from "./staffUploadHarness";

export type ConsoleKind = "generic" | "printer";
export function serviceType(kind: ConsoleKind, id = kind === "printer" ? 2 : 1): MachineType {
  return {
    id, slug: kind === "printer" ? "3d_printer" : "press", name: kind === "printer" ? "Printers" : "Presses",
    icon: "", is_builtin: kind === "printer", managing_action: "manage_machines", makerspace: kind === "printer" ? null : 1,
    capability_config: { metering_unit: kind === "printer" ? "weight" : "count", requires_booking: false, uses_consumables: kind === "printer" },
  };
}
export function serviceMachine(type: MachineType, id = 11): Machine {
  return {
    id, makerspace: 1, machine_type: type, name: `Machine ${id}`, location: "Lab", notes: "", status: "idle",
    firmware_version: "", camera_feed_url: "", image_url: null, warranty_status: "unknown", is_public: true,
    is_active: true, usage_hours: "0", can_operate: true, can_edit: true, can_delegate: true,
    can_retire: true, can_unretire: false, can_manage: true, created_at: "", updated_at: "",
  };
}
export function filledServiceDraft(id = 4): ServiceDraft {
  const draft = blankServiceDraft();
  return {
    ...draft, action: { id, name: "fail" },
    actionValues: { ...draft.actionValues, machine_id: "11", actual_minutes: "23", actual_quantity: "4.5", percent_complete: "35", reason: "Broken fixture" },
    manual: { ...draft.manual, machine_id: "11", duration_minutes: "17", quantity: "2.25", outcome: "failed", percent_complete: "40", reason: "Jam", note: "Click-time note", price: "12.50" },
  };
}
export function serviceJob(id = 4, kind: ConsoleKind = "generic"): MachineServiceRequest {
  return {
    id, bucket_id: 1, queue_id: 1, allocation_policy: "staff_select", machine_type: kind === "printer" ? "3d_printer" : "press", machine: { id: 11, name: "Machine 11", status: "running" },
    assigned_machine: { id: 11, name: "Machine 11", status: "running" }, requester: { id: 1, username: "maker", display: "Maker" },
    requester_name: "Maker", contact_email: "maker@example.test", contact_phone: "", title: id === 4 ? "Job A" : "Job B",
    description: "Fixture job", source_link: "", status: "in_progress", reason: "", estimated_minutes: 60,
    actual_minutes: 0, fail_percent_complete: 0, accepted_at: null, started_at: null, completed_at: null, failed_at: null,
    collected_at: null, created_at: "2026-01-02", updated_at: "2026-01-02", capability_payload: {}, metering_unit: kind === "printer" ? "weight" : "count",
    planned_quantity: "5", reserved_quantity: "5", actual_consumed_quantity: "0", planned_grams: "5", reserved_grams: "5",
    actual_consumed_grams: "0", payment: null, payment_amount: null, payment_status: "none", paid_at: null, run_machine_model: "",
    files: [], consumptions: [],
  };
}
export function servicePool(_type: MachineType): PrinterPool {
  return { id: 31, machine_id: 11, machine_type_id: null, material: "PLA", color: "", brand: "", unit: "grams",
    initial_grams: "1000", remaining_grams: "800", is_active: true, created_at: "", updated_at: "" };
}

export function ServiceConsoleHarness({ kind = "generic", typeId, initial = filledServiceDraft(), replacement }: {
  kind?: ConsoleKind; typeId?: number; initial?: ServiceDraft; replacement?: ServiceDraft;
}) {
  const [draft, setDraft] = useState(initial);
  useEffect(() => { if (replacement) setDraft(replacement); }, [replacement]);
  const type = serviceType(kind, typeId);
  const props = { makerspaceId: 1, canManage: true, machineType: type, machines: [serviceMachine(type)], pools: [servicePool(type)], draft, setDraft };
  return <>
    {kind === "printer" ? <PrinterServiceConsole {...props} printingEnabled reportsEnabled={false} /> : <MachineServiceConsole {...props} />}
    <pre data-testid="draft">{JSON.stringify(draft)}</pre>
  </>;
}
export function observedDraft(): ServiceDraft { return JSON.parse(screen.getByTestId("draft").textContent ?? "null") as ServiceDraft; }
export function setValue(label: string, value: string) { fireEvent.change(screen.getByLabelText(label), { target: { value } }); }

// Synthetic HTTP leaves contain ordinary server DTOs, never ownership or epoch checks.
export function serviceRead(call: HttpCall): Response {
  if (call.path === "/admin/makerspaces") return json(machineTestMakerspaces());
  if (call.path.includes("/machine-type-pricing")) return json({ currency: "inr", results: [] });
  if (call.path.includes("machine-service-report")) return json({ printer_metrics: [] });
  if (call.path.includes("/requests?")) {
    const kind = new URLSearchParams(call.path.split("?")[1]).get("machine_type_id") === "2" ? "printer" : "generic";
    return json([serviceJob(4, kind), serviceJob(5, kind)]);
  }
  if (call.method === "GET") return json([]);
  return json({ id: 4 });
}
