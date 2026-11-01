import { QueryClient } from "@tanstack/react-query";
import type { ComponentProps } from "react";
import { MemoryRouter, useLocation, useNavigate } from "react-router-dom";
import type { MachineServiceRequest } from "../../../generated/api";
import { serviceJob, serviceMachine, serviceRead, serviceType, type ConsoleKind } from "../../../test/staffServiceOwnershipHarness";
import { json, mountStaff, type HttpCall } from "../../../test/staffUploadHarness";
import { MachinesPanel } from "./MachinesPanel";

export function queueType(kind: ConsoleKind = "generic", id?: number) {
  return { ...serviceType(kind, id), can_create_machine: true,
    capability_config: { metering_unit: kind === "printer" ? "weight" as const : "count" as const,
      requires_booking: false, uses_consumables: true } };
}
export const queueTypes = [queueType(), queueType("printer")];
// Observe the real query lifecycle; never seed data or extend test/assertion timeouts.
export function queryDataReady(client: QueryClient, key: readonly unknown[]) {
  return new Promise<void>((resolve, reject) => {
    const check = () => {
      const state = client.getQueryState(key);
      if (state?.status === "success") { unsubscribe(); resolve(); }
      else if (state?.status === "error") { unsubscribe(); reject(state.error); }
    };
    const unsubscribe = client.getQueryCache().subscribe(check);
    check();
  });
}

export function queueRead(call: HttpCall, jobs: MachineServiceRequest[] = [serviceJob()]) {
  if (call.path.endsWith("/machine-types")) return json(queueTypes);
  if (call.path.endsWith("/machines")) return json({ count: 2, next: null, previous: null,
    results: queueTypes.map((type, index) => serviceMachine(type, index + 11)) });
  if (call.path === "/admin/machines/11") return json(serviceMachine(queueTypes[0]));
  if (call.path.includes("/requests?")) return json(jobs);
  return serviceRead(call);
}
function RouterControls() {
  const navigate = useNavigate();
  return <><output aria-label="Current path">{useLocation().pathname}</output>
    <button onClick={() => navigate(-1)}>Browser back</button>
    <button onClick={() => navigate(1)}>Browser forward</button></>;
}
export function mountQueuePanel(route = "/admin/machines/1-press/queue", props: Partial<ComponentProps<typeof MachinesPanel>> = {}, client?: QueryClient) {
  return mountStaff(<MemoryRouter initialEntries={[route]}><RouterControls />
    <MachinesPanel makerspaceId={1} canManage canConfigureMachineTypes={false} maintenanceEnabled={false}
      machineServiceEnabled printingEnabled reportsEnabled={false} delegatedRecipientRulesEnabled={false} {...props} />
  </MemoryRouter>, client);
}
