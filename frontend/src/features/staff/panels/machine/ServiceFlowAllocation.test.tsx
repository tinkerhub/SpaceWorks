import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { MachineServiceRequest } from "../../../../generated/api";
import { servicePool, serviceType, type ConsoleKind } from "../../../../test/staffServiceOwnershipHarness";
import { blankServiceDraft } from "./serviceDrafts";
import {
  acceptedJob, actionForm, dropdown, editField, FlowConsole, flowLifecycle, jobArticle, mountFlow, pickOption, queueHttp,
} from "./serviceFlowTestHarness";

flowLifecycle();

describe.each<ConsoleKind>(["generic", "printer"])("%s start allocation", (kind) => {
  const noun = kind === "printer" ? "Printer" : "Machine";
  it.each(["staff_select", "unknown", "missing", "legacy"] as const)("%s requires a scoped selection and preserves the accepted estimate", async (policy) => {
    const dto: Record<string, unknown> = { ...acceptedJob(kind) };
    if (policy === "missing") delete dto.allocation_policy;
    else if (policy === "legacy") { dto.queue_id = null; dto.allocation_policy = "staff_select"; }
    else dto.allocation_policy = policy;
    // Deliberately exercise old/unknown HTTP DTOs at the boundary of the typed client.
    const net = queueHttp([dto as unknown as MachineServiceRequest]);
    mountFlow(<FlowConsole kind={kind} />);
    const article = await jobArticle();
    fireEvent.click(within(article).getByRole("button", { name: "Start" }));
    const form = actionForm(article);
    expect(within(form).getByLabelText("Estimated minutes")).toHaveValue("10");
    expect(dropdown(form, noun)).toHaveTextContent(`Choose a ${noun.toLowerCase()}`);
    expect(dropdown(form, noun)).toHaveAttribute("aria-required", "true");
    expect(within(form).getByRole("button", { name: "Start job" })).toBeDisabled();
    fireEvent.submit(form); // Exercise the submit guard even when native validity is bypassed.
    expect(net.writes()).toHaveLength(0);
    pickOption(form, noun, "Machine 11");
    if (kind === "printer") {
      pickOption(form, "Pool", "PLA");
      editField(form, "Planned quantity (g)", "12");
    }
    expect(within(form).getByRole("button", { name: "Start job" })).toBeEnabled();
    fireEvent.click(within(form).getByRole("button", { name: "Start job" }));
    await waitFor(() => expect(net.writes()).toHaveLength(1));
    expect(net.writes()[0].path).toBe("/admin/machine-service/requests/4/start");
    expect(net.writes()[0].body).toEqual({ machine_id: 11, estimated_minutes: 10,
      ...(kind === "printer" ? { consumable_pool_id: 31, planned_grams: "12" } : {}) });
    expect(await screen.findByText("Job started", { exact: true })).toBeVisible();
  });

  it.each([false, true])("first_idle permits blank while honoring an explicit selection=%s", async (selected) => {
    const net = queueHttp([{ ...acceptedJob(kind), allocation_policy: "first_idle" }]);
    const type = serviceType(kind);
    // Blank automatic allocation needs real unbound stock; explicit allocation uses bound stock.
    const pool = selected ? servicePool(type) : { ...servicePool(type), machine_id: null, machine_type_id: type.id };
    mountFlow(<FlowConsole kind={kind} type={type} pools={[pool]} />);
    const article = await jobArticle();
    fireEvent.click(within(article).getByRole("button", { name: "Start" }));
    const form = actionForm(article);
    expect(dropdown(form, noun)).toHaveTextContent(`Any idle ${noun.toLowerCase()}`);
    expect(within(form).getByLabelText("Estimated minutes")).toHaveValue("10");
    expect(within(form).getByRole("button", { name: "Start job" })).toBeEnabled();
    if (selected) pickOption(form, noun, "Machine 11");
    if (kind === "printer") {
      pickOption(form, "Pool", "PLA");
      editField(form, "Planned quantity (g)", "12");
    }
    fireEvent.click(within(form).getByRole("button", { name: "Start job" }));
    await waitFor(() => expect(net.writes()).toHaveLength(1));
    expect(net.writes()[0].path).toBe("/admin/machine-service/requests/4/start");
    expect(net.writes()[0].body).toEqual({ machine_id: selected ? 11 : null, estimated_minutes: 10,
      ...(kind === "printer" ? { consumable_pool_id: 31, planned_grams: "12" } : {}) });
    expect(await screen.findByText("Job started", { exact: true })).toBeVisible();
  });

  it("fails closed when the retained Start draft's request has left the queue", async () => {
    const draft = blankServiceDraft();
    draft.action = { id: 99, name: "start" };
    const net = queueHttp([]);
    mountFlow(<FlowConsole kind={kind} initial={draft} />);
    await screen.findByText("The queue is clear");
    const submit = screen.getByRole("button", { name: "Start job" });
    expect(submit).toBeDisabled();
    expect(dropdown(submit.closest("form")!, noun)).toHaveTextContent(`Choose a ${noun.toLowerCase()}`);
    fireEvent.submit(submit.closest("form")!);
    expect(net.writes()).toHaveLength(0);
  });
});
