import { fireEvent, within } from "@testing-library/react";
import { expect, it } from "vitest";
import { serviceType } from "../../../../test/staffServiceOwnershipHarness";
import { acceptedJob, actionForm, FlowConsole, flowLifecycle, jobArticle, mountFlow, queueHttp } from "./serviceFlowTestHarness";

flowLifecycle();

it.each([null, "20"])("uses effective minutes for planned and actual time despite quantity=%s", async (quantity) => {
  const type = serviceType("generic");
  // Exercise the actual effective-config precedence over the legacy count configuration.
  type.effective_config = { metering_unit: "minutes", requires_booking: false, uses_consumables: false, overridden: true };
  queueHttp([{ ...acceptedJob("generic"), status: "completed", actual_minutes: 8,
    planned_quantity: quantity, actual_consumed_quantity: quantity }]);
  mountFlow(<FlowConsole type={type} />);
  const article = await jobArticle();
  expect(within(article).getByText("Planned 10 minutes · actual 8 minutes", { exact: true })).toBeVisible();
  expect(within(article).queryByText(/20 minutes/)).not.toBeInTheDocument();
});

it("renders accepted zero actual minutes and the matching time-only Start form", async () => {
  const type = serviceType("generic");
  type.effective_config = { metering_unit: "minutes", requires_booking: false, uses_consumables: false, overridden: true };
  queueHttp([{ ...acceptedJob("generic"), actual_minutes: 0, planned_quantity: "20", actual_consumed_quantity: "20" }]);
  mountFlow(<FlowConsole type={type} />);
  const article = await jobArticle();
  expect(within(article).getByText("Planned 10 minutes · actual 0 minutes", { exact: true })).toBeVisible();
  fireEvent.click(within(article).getByRole("button", { name: "Start" }));
  expect(within(actionForm(article)).getByLabelText("Estimated minutes")).toHaveValue("10");
  expect(within(actionForm(article)).queryByLabelText(/Planned quantity/)).not.toBeInTheDocument();
  expect(within(actionForm(article)).queryByLabelText("Pool")).not.toBeInTheDocument();
});

it.each([
  ["count", "count", "items"], ["length", "millimeters", "mm"],
] as const)("keeps %s metadata and form quantities in their own units", async (unit, label, short) => {
  const type = serviceType("generic");
  type.effective_config = { metering_unit: unit, requires_booking: false, uses_consumables: false, overridden: true };
  queueHttp([{ ...acceptedJob("generic"), actual_minutes: 8, planned_quantity: "20", actual_consumed_quantity: "7" }]);
  mountFlow(<FlowConsole type={type} />);
  const article = await jobArticle();
  expect(within(article).getByText(`Planned 20 ${label} · actual 7 ${label}`, { exact: true })).toBeVisible();
  fireEvent.click(within(article).getByRole("button", { name: "Start" }));
  expect(within(actionForm(article)).getByLabelText(`Planned quantity (${short})`)).toBeVisible();
  expect(within(actionForm(article)).getByLabelText("Estimated minutes")).toHaveValue("10");
});
