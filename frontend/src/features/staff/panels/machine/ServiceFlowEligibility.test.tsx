import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Machine } from "../../machinesApi";
import { serviceMachine, serviceType, type ConsoleKind } from "../../../../test/staffServiceOwnershipHarness";
import {
  acceptedJob, actionForm, dropdown, FlowConsole, flowLifecycle, jobArticle, mountFlow, pickOption, queueHttp,
} from "./serviceFlowTestHarness";

flowLifecycle();

describe.each<ConsoleKind>(["generic", "printer"])("%s start machine eligibility", (kind) => {
  const type = serviceType(kind);
  const noun = kind === "printer" ? "Printer" : "Machine";
  const idle = serviceMachine(type);
  const unavailable: Machine[] = [
    ...(["running", "reserved", "maintenance", "offline"] as const).map((status, index) =>
      ({ ...serviceMachine(type, 20 + index), status })),
    { ...serviceMachine(type, 24), name: "Retired", is_active: false, status: "idle" },
  ];
  async function startForm() {
    const article = await jobArticle();
    fireEvent.click(within(article).getByRole("button", { name: "Start" }));
    return actionForm(article);
  }

  it("offers only active idle machines for Start but keeps historical machines in manual usage", async () => {
    queueHttp([acceptedJob(kind)]);
    mountFlow(<FlowConsole kind={kind} machines={[idle, ...unavailable]} />);
    const form = await startForm();
    fireEvent.click(dropdown(form, noun));
    const options = within(screen.getByRole("listbox"));
    expect(options.getAllByRole("option").map((option) => option.textContent)).toEqual([
      `Choose a ${noun.toLowerCase()}`, "Machine 11",
    ]);
    fireEvent.keyDown(screen.getByRole("listbox"), { key: "Escape" });
    // Status filtering belongs to Start; it must not hide a past run from manual history.
    fireEvent.click(screen.getByRole("combobox", { name: `Manual usage ${noun.toLowerCase()}` }));
    for (const machine of unavailable) {
      expect(within(screen.getByRole("listbox")).getByRole("option", { name: machine.name })).toBeVisible();
    }
  });

  it.each(["staff_select", "first_idle"] as const)("blocks a previously eligible saved selection after list refresh for %s", async (allocation_policy) => {
    const net = queueHttp([{ ...acceptedJob(kind), allocation_policy }]);
    const view = mountFlow(<FlowConsole kind={kind} machines={[idle]} />);
    let form = await startForm();
    pickOption(form, noun, "Machine 11");
    expect(within(form).getByRole("button", { name: "Start job" })).toBeEnabled();
    // Another idle machine exists: a stale explicit selection must not silently become
    // automatic allocation, even when this request permits first_idle.
    view.rerender(<FlowConsole kind={kind} machines={[{ ...idle, status: "running" }, serviceMachine(type, 12)]} />);
    form = actionForm(await jobArticle());
    expect(dropdown(form, noun)).toHaveTextContent("Previously selected");
    expect(within(form).getByRole("alert")).toHaveTextContent("no longer eligible");
    expect(within(form).getByRole("button", { name: "Start job" })).toBeDisabled();
    fireEvent.submit(form);
    expect(net.writes()).toHaveLength(0);
    if (allocation_policy === "first_idle") pickOption(form, noun, `Any idle ${noun.toLowerCase()}`);
    else pickOption(form, noun, "Machine 12");
    expect(within(form).getByRole("button", { name: "Start job" })).toBeEnabled();
    expect(within(form).queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps blank first_idle disabled without any eligible machine and enables it after a fresh list", async () => {
    const net = queueHttp([{ ...acceptedJob(kind), allocation_policy: "first_idle" }]);
    const view = mountFlow(<FlowConsole kind={kind} machines={unavailable} />);
    const form = await startForm();
    expect(dropdown(form, noun)).toHaveTextContent(`Any idle ${noun.toLowerCase()}`);
    expect(within(form).getByRole("status")).toHaveTextContent("No active idle");
    expect(within(form).getByRole("button", { name: "Start job" })).toBeDisabled();
    fireEvent.submit(form);
    expect(net.writes()).toHaveLength(0);
    view.rerender(<FlowConsole kind={kind} machines={[...unavailable, idle]} />);
    expect(within(form).getByRole("button", { name: "Start job" })).toBeEnabled();
    expect(dropdown(form, noun)).toHaveTextContent(`Any idle ${noun.toLowerCase()}`);
  });

  it.each(["status", "is_active"] as const)("fails closed when a sparse server machine is missing %s", async (field) => {
    const dto: Record<string, unknown> = { ...idle };
    delete dto[field];
    const net = queueHttp([{ ...acceptedJob(kind), allocation_policy: "first_idle" }]);
    // Deliberate malformed DTO coverage: production must not infer eligibility from absence.
    mountFlow(<FlowConsole kind={kind} machines={[dto as unknown as Machine]} />);
    const form = await startForm();
    expect(within(form).getByRole("button", { name: "Start job" })).toBeDisabled();
    fireEvent.submit(form);
    expect(net.writes()).toHaveLength(0);
  });
});
