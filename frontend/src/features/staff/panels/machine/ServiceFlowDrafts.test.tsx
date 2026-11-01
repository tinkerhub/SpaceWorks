import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { MachineServiceRequest } from "../../../../generated/api";
import { observedDraft, serviceJob, serviceType, type ConsoleKind } from "../../../../test/staffServiceOwnershipHarness";
import {
  acceptedJob, actionForm, dropdown, editField, FlowConsole, flowLifecycle, jobArticle, mountFlow, pickOption, queueHttp,
} from "./serviceFlowTestHarness";

flowLifecycle();

describe.each<ConsoleKind>(["generic", "printer"])("%s stateful action drafts", (kind) => {
  const noun = kind === "printer" ? "Printer" : "Machine";
  const type = serviceType(kind);
  type.capability_config = { metering_unit: "weight", requires_booking: false, uses_consumables: true };
  const openStart = (article: HTMLElement) => {
    fireEvent.click(within(article).getByRole("button", { name: "Start" }));
    return actionForm(article);
  };
  function fillStart(form: HTMLElement) {
    pickOption(form, noun, "Machine 11");
    pickOption(form, "Pool", "PLA");
    editField(form, "Planned quantity (g)", "22");
    editField(form, "Estimated minutes", "17");
  }
  function expectFreshStart(form: HTMLElement, estimate: string) {
    expect(dropdown(form, noun)).toHaveTextContent(`Choose a ${noun.toLowerCase()}`);
    expect(dropdown(form, "Pool")).toHaveTextContent("No pool");
    expect(within(form).getByLabelText("Planned quantity (g)")).toHaveValue("");
    expect(within(form).getByLabelText("Estimated minutes")).toHaveValue(estimate);
  }

  it("switches jobs with fresh machine, pool and quantity, seeded from the destination estimate", async () => {
    queueHttp([acceptedJob(kind), acceptedJob(kind, 5, 25)]);
    mountFlow(<FlowConsole kind={kind} type={type} />);
    fillStart(openStart(await jobArticle()));
    const second = await jobArticle("Job B");
    expectFreshStart(openStart(second), "25");
    expect(observedDraft().action).toEqual({ id: 5, name: "start" });
  });

  it("keeps operator edits when the same job and action is chosen again", async () => {
    queueHttp([acceptedJob(kind)]);
    mountFlow(<FlowConsole kind={kind} type={type} />);
    const article = await jobArticle();
    fillStart(openStart(article));
    const form = openStart(article);
    expect(dropdown(form, noun)).toHaveTextContent("Machine 11");
    expect(dropdown(form, "Pool")).toHaveTextContent("PLA");
    expect(within(form).getByLabelText("Planned quantity (g)")).toHaveValue("22");
    expect(within(form).getByLabelText("Estimated minutes")).toHaveValue("17");
  });

  it("preserves a repeated Fail edit but clears actual quantity and reason when changing action", async () => {
    queueHttp([serviceJob(4, kind)]);
    mountFlow(<FlowConsole kind={kind} type={type} />);
    const article = await jobArticle();
    const fail = within(article).getByRole("button", { name: "Fail…" });
    fireEvent.click(fail);
    const form = actionForm(article);
    editField(form, "Actual minutes", "8");
    editField(form, "Actual quantity (g)", "6");
    editField(form, "Percent complete", "30");
    editField(form, "Reason", "Jammed nozzle");
    fireEvent.click(fail);
    expect(within(form).getByLabelText("Reason")).toHaveValue("Jammed nozzle");
    expect(within(form).getByLabelText("Actual minutes")).toHaveValue("8");
    expect(within(form).getByLabelText("Actual quantity (g)")).toHaveValue("6");
    fireEvent.click(within(article).getByRole("button", { name: "Complete" }));
    expect(within(actionForm(article)).getByLabelText("Actual minutes")).toHaveValue("0");
    expect(within(actionForm(article)).getByLabelText("Actual quantity (g)")).toHaveValue("");
    expect(within(article).queryByLabelText("Reason")).not.toBeInTheDocument();
    expect(observedDraft().actionValues).toMatchObject({ reason: "", percent_complete: "0", machine_id: "", consumable_pool_id: "" });
  });

  it("cancel and reopen discard machine, stock and quantity edits and restore the stored estimate", async () => {
    queueHttp([acceptedJob(kind)]);
    mountFlow(<FlowConsole kind={kind} type={type} />);
    const article = await jobArticle();
    fillStart(openStart(article));
    fireEvent.click(within(actionForm(article)).getByRole("button", { name: "Cancel" }));
    expect(article.querySelector("form")).toBeNull();
    expectFreshStart(openStart(article), "10");
  });

  it("does not carry the successful previous job's machine, pool or quantity into another job", async () => {
    const net = queueHttp([acceptedJob(kind), acceptedJob(kind, 5, 25)]);
    mountFlow(<FlowConsole kind={kind} type={type} />);
    const article = await jobArticle();
    fillStart(openStart(article));
    fireEvent.click(within(actionForm(article)).getByRole("button", { name: "Start job" }));
    await screen.findByText("Job started", { exact: true });
    await waitFor(() => expect(observedDraft().action).toBeNull());
    expect(net.writes()[0].body).toEqual({ machine_id: 11, consumable_pool_id: 31, estimated_minutes: 17,
      ...(kind === "printer" ? { planned_grams: "22" } : { planned_quantity: "22" }) });
    expectFreshStart(openStart(await jobArticle("Job B")), "25");
  });

  it.each([0, undefined])("preserves estimate %s, falling back only for a missing estimate", async (estimate) => {
    const dto = { ...acceptedJob(kind), estimated_minutes: estimate } as unknown as MachineServiceRequest;
    queueHttp([dto]);
    mountFlow(<FlowConsole kind={kind} type={type} />);
    expectFreshStart(openStart(await jobArticle()), estimate === 0 ? "0" : "60");
  });
});
