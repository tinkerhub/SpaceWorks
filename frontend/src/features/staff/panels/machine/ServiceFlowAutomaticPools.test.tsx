import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { MachineServiceRequest, PrinterPool } from "../../../../generated/api";
import { observedDraft, servicePool, serviceType, type ConsoleKind } from "../../../../test/staffServiceOwnershipHarness";
import { blankServiceDraft } from "./serviceDrafts";
import {
  acceptedJob, actionForm, dropdown, editField, FlowConsole, flowLifecycle, jobArticle, mountFlow, pickOption, queueHttp,
} from "./serviceFlowTestHarness";

flowLifecycle();

function expectPoolChoices(form: HTMLElement, names: string[]) {
  fireEvent.click(dropdown(form, "Pool"));
  const list = within(screen.getByRole("listbox"));
  expect(list.getAllByRole("option").map((option) => option.textContent)).toEqual(["No pool", ...names]);
  fireEvent.click(list.getByRole("option", { name: "No pool" }));
}

describe.each<ConsoleKind>(["generic", "printer"])("%s automatic stock in the real console", (kind) => {
  const noun = kind === "printer" ? "Printer" : "Machine";
  const shortUnit = kind === "printer" ? "g" : "items";
  const unit = kind === "printer" ? "grams" : "count";
  const type = serviceType(kind);
  type.capability_config = {
    metering_unit: kind === "printer" ? "weight" : "count", uses_consumables: true, requires_booking: false,
  };
  function stocks(): PrinterPool[] {
    const base: PrinterPool = { ...servicePool(type), unit, machine_id: null, machine_type_id: type.id };
    return [
      { ...base, id: 31, material: "Type stock" },
      { ...base, id: 32, material: "Bound stock", machine_id: 11, machine_type_id: null },
      { ...base, id: 33, material: "Other type stock", machine_type_id: 99 },
      { ...base, id: 34, material: "Legacy stock", machine_type_id: null },
    ];
  }
  async function openStart() {
    const article = await jobArticle();
    fireEvent.click(within(article).getByRole("button", { name: "Start" }));
    return actionForm(article);
  }

  it("starts first_idle with visible type-wide stock, a typed quantity and no machine", async () => {
    const net = queueHttp([{ ...acceptedJob(kind), allocation_policy: "first_idle" }]);
    mountFlow(<FlowConsole kind={kind} type={type} pools={stocks()} />);
    const form = await openStart();
    expect(dropdown(form, noun)).toHaveTextContent(`Any idle ${noun.toLowerCase()}`);
    expect(within(form).getByText("Choose stock for this machine type.")).toBeVisible();
    expect(within(form).getByLabelText("Estimated minutes")).toHaveValue("10");
    expect(observedDraft().actionValues.consumable_pool_id).toBe("");
    expectPoolChoices(form, ["Type stock", "Legacy stock"]);
    pickOption(form, "Pool", "Type stock");
    editField(form, `Planned quantity (${shortUnit})`, "12");
    fireEvent.click(within(form).getByRole("button", { name: "Start job" }));
    await waitFor(() => expect(net.writes()).toHaveLength(1));
    expect(net.writes()[0]).toMatchObject({ method: "POST", path: "/admin/machine-service/requests/4/start" });
    expect(net.writes()[0].body).toEqual({ machine_id: null, consumable_pool_id: 31, estimated_minutes: 10,
      ...(kind === "printer" ? { planned_grams: "12" } : { planned_quantity: "12" }) });
    expect(await screen.findByText("Job started", { exact: true })).toBeVisible();
  });

  it.each(["staff_select", "unknown", "missing", "legacy"] as const)("does not offer automatic stock for server policy %s", async (policy) => {
    const dto: Record<string, unknown> = { ...acceptedJob(kind) };
    if (policy === "missing") delete dto.allocation_policy;
    else if (policy === "legacy") { dto.queue_id = null; dto.allocation_policy = "staff_select"; }
    else dto.allocation_policy = policy;
    const net = queueHttp([dto as unknown as MachineServiceRequest]);
    mountFlow(<FlowConsole kind={kind} type={type} pools={stocks()} />);
    const form = await openStart();
    expectPoolChoices(form, []);
    expect(dropdown(form, noun)).toHaveAttribute("aria-required", "true");
    expect(within(form).getByText(`Choose a ${noun.toLowerCase()} to see its pools.`)).toBeVisible();
    expect(within(form).getByRole("button", { name: "Start job" })).toBeDisabled();
    fireEvent.submit(form);
    expect(net.writes()).toHaveLength(0);
  });

  it("does not offer automatic stock to a retained draft whose request is absent", async () => {
    const draft = blankServiceDraft();
    draft.action = { id: 99, name: "start" };
    const net = queueHttp([]);
    mountFlow(<FlowConsole kind={kind} type={type} pools={stocks()} initial={draft} />);
    await screen.findByText("The queue is clear");
    const submit = screen.getByRole("button", { name: "Start job" });
    const form = submit.closest("form")!;
    expectPoolChoices(form, []);
    expect(dropdown(form, noun)).toHaveAttribute("aria-required", "true");
    expect(submit).toBeDisabled();
    fireEvent.submit(form);
    expect(net.writes()).toHaveLength(0);
  });

  it("clears chosen stock on machine changes and exposes bound stock only with its machine", async () => {
    queueHttp([{ ...acceptedJob(kind), allocation_policy: "first_idle" }]);
    mountFlow(<FlowConsole kind={kind} type={type} pools={stocks()} />);
    const form = await openStart();
    pickOption(form, "Pool", "Type stock");
    expect(dropdown(form, "Pool")).toHaveTextContent("Type stock");
    expect(observedDraft().actionValues.consumable_pool_id).toBe("31");
    pickOption(form, noun, "Machine 11");
    expect(dropdown(form, "Pool")).toHaveTextContent("No pool");
    expect(observedDraft().actionValues).toMatchObject({ machine_id: "11", consumable_pool_id: "" });
    expectPoolChoices(form, ["Type stock", "Bound stock", "Legacy stock"]);
    pickOption(form, "Pool", "Bound stock");
    expect(dropdown(form, "Pool")).toHaveTextContent("Bound stock");
    expect(observedDraft().actionValues.consumable_pool_id).toBe("32");
    pickOption(form, noun, `Any idle ${noun.toLowerCase()}`);
    expect(dropdown(form, "Pool")).toHaveTextContent("No pool");
    expect(observedDraft().actionValues).toMatchObject({ machine_id: "", consumable_pool_id: "" });
    expectPoolChoices(form, ["Type stock", "Legacy stock"]);
  });

  it("keeps manual usage stock empty while first_idle start offers type stock", async () => {
    queueHttp([{ ...acceptedJob(kind), allocation_policy: "first_idle" }]);
    mountFlow(<FlowConsole kind={kind} type={type} pools={stocks()} />);
    const form = await openStart();
    expectPoolChoices(form, ["Type stock", "Legacy stock"]);
    fireEvent.click(screen.getByRole("combobox", { name: "Manual usage pool" }));
    const list = within(screen.getByRole("listbox"));
    expect(list.getAllByRole("option")).toHaveLength(1);
    expect(list.getByRole("option", { name: "No pool" })).toBeVisible();
  });
});
