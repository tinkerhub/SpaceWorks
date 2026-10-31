import { render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import { StatusStepper } from "./StatusStepper";

it("cancelled is a neutral terminal status with no collection or request progression", () => {
  render(<StatusStepper status="cancelled" />);
  const progress = screen.getByRole("navigation", { name: "Request status: Cancelled" });
  const label = within(progress).getByText("Cancelled");
  expect(label.parentElement).toHaveClass("bg-fill", "text-ink-secondary");
  expect(within(progress).queryByRole("list")).not.toBeInTheDocument();
  for (const stage of ["Requested", "Approved", "Collected", "Returned"]) {
    expect(within(progress).queryByText(stage)).not.toBeInTheDocument();
  }
  expect(progress.querySelector('[aria-current="step"]')).toBeNull();
});

it("moving from an approved request to cancellation replaces the progress steps", () => {
  const view = render(<StatusStepper status="accepted" />);
  const approved = screen.getByRole("navigation", { name: "Request status: Approved" });
  expect(within(approved).getAllByRole("listitem")).toHaveLength(4);
  expect(within(approved).getByText("Approved").parentElement).toHaveAttribute("aria-current", "step");
  view.rerender(<StatusStepper status="cancelled" />);
  expect(screen.getByRole("navigation", { name: "Request status: Cancelled" })).toHaveTextContent("Cancelled");
  expect(screen.queryByRole("listitem")).not.toBeInTheDocument();
  expect(screen.queryByText("Collected")).not.toBeInTheDocument();
});
