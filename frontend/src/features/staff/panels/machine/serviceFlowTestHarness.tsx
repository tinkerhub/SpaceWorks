import { onlineManager, type QueryClient } from "@tanstack/react-query";
import { fireEvent, screen, within } from "@testing-library/react";
import { useState, type ReactNode } from "react";
import { afterEach, beforeEach, expect } from "vitest";

import type { MachineServiceRequest, PrinterPool } from "../../../../generated/api";
import {
  serviceJob, serviceMachine, servicePool, serviceRead, serviceType, type ConsoleKind,
} from "../../../../test/staffServiceOwnershipHarness";
import { cleanUploadSession, http, json, mountStaff, resetUploadSession } from "../../../../test/staffUploadHarness";
import type { Machine, MachineType } from "../../machinesApi";
import { MachineServiceConsole } from "./MachineServiceConsole";
import { PrinterServiceConsole } from "./PrinterServiceConsole";
import { blankServiceDraft, type ServiceDraft } from "./serviceDrafts";

const clients: QueryClient[] = [];
export function flowLifecycle() {
  let online: boolean;
  beforeEach(() => { online = onlineManager.isOnline(); resetUploadSession(); });
  afterEach(() => {
    onlineManager.setOnline(online);
    cleanUploadSession();
    clients.splice(0).forEach((client) => client.clear());
  });
}
export function mountFlow(ui: ReactNode) {
  const view = mountStaff(ui);
  clients.push(view.client);
  return view;
}
export function FlowConsole({ kind = "generic", type = serviceType(kind), initial = blankServiceDraft(), pools = [servicePool(type)], machines = [serviceMachine(type)] }: {
  kind?: ConsoleKind; type?: MachineType; initial?: ServiceDraft; pools?: PrinterPool[]; machines?: Machine[];
}) {
  const [draft, setDraft] = useState(initial);
  const props = { makerspaceId: 1, canManage: true, machineType: type,
    machines, pools, draft, setDraft };
  return <>
    {kind === "printer"
      ? <PrinterServiceConsole {...props} printingEnabled reportsEnabled={false} />
      : <MachineServiceConsole {...props} />}
    <pre data-testid="draft">{JSON.stringify(draft)}</pre>
  </>;
}
export function acceptedJob(kind: ConsoleKind, id = 4, estimate = 10): MachineServiceRequest {
  return { ...serviceJob(id, kind), status: "accepted", estimated_minutes: estimate };
}
export function queueHttp(jobs: MachineServiceRequest[] | (() => MachineServiceRequest[])) {
  return http((call) => call.path.includes("/requests?")
    ? json(typeof jobs === "function" ? jobs() : jobs) : serviceRead(call));
}
export async function jobArticle(title = "Job A") {
  return (await screen.findByText(title, { exact: true })).closest("article")!;
}
export function actionForm(article: HTMLElement) {
  const form = article.querySelector("form");
  if (!form) throw new Error("Missing job action form");
  return form;
}
export function editField(container: HTMLElement, label: string, value: string) {
  fireEvent.change(within(container).getByLabelText(label), { target: { value } });
}
export function dropdown(container: HTMLElement, label: string) {
  return within(container).getByLabelText(label, { selector: "button" });
}
export function pickOption(container: HTMLElement, label: string, name: string) {
  const trigger = dropdown(container, label);
  expect(trigger).toBeVisible();
  expect(trigger).toHaveRole("combobox");
  fireEvent.click(trigger);
  const option = within(screen.getByRole("listbox")).getByRole("option", { name });
  expect(option).toBeVisible();
  fireEvent.click(option);
}
