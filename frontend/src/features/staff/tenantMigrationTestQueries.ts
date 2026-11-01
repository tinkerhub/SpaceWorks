import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { expect } from "vitest";

type MigrationStep = "Source export" | "Deployment pairing" | "Target import";
type Queries = ReturnType<typeof within>;

export function selectMigrationStep(name: MigrationStep) {
  const tabs = within(screen.getByRole("tablist", { name: "Migration steps" }));
  const tab = tabs.getByRole("tab", { name });
  expect(tab).toBeVisible();
  fireEvent.mouseDown(tab, { button: 0, ctrlKey: false });
  fireEvent.click(tab);
  expect(tab).toHaveAttribute("aria-selected", "true");
  const panel = screen.getByRole("tabpanel", { name });
  expect(panel.id).toBe(tab.getAttribute("aria-controls"));
  expect(panel).toHaveAttribute("aria-labelledby", tab.id);
  // forceMount keeps inactive panels in jsdom even without Tailwind's hiding rule.
  expect(panel).toHaveAttribute("data-state", "active");
  expect(panel).toBeVisible();
  return within(panel);
}

export async function chooseMigrationOption(scope: Queries, label: string, name: string) {
  const trigger = scope.getByLabelText(label, { exact: true, selector: "button" });
  expect(trigger).toHaveRole("combobox");
  expect(trigger).toHaveAccessibleName(label);
  expect(trigger).toBeVisible();
  fireEvent.click(trigger);
  const listbox = await screen.findByRole("listbox");
  expect(listbox).toBeVisible();
  const option = within(listbox).getByRole("option", { name });
  expect(option).toBeVisible();
  fireEvent.click(option);
}

export async function findMigrationButton(scope: Queries, name: string) {
  const text = await scope.findByText(name, { exact: true });
  const button = text.closest("button");
  expect(button).toHaveRole("button");
  expect(button).toHaveAccessibleName(name);
  expect(button).toBeVisible();
  return button!;
}

export async function migrationDialog(title: RegExp) {
  const dialog = await screen.findByRole("alertdialog", { name: title });
  expect(dialog).toBeVisible();
  expect(within(dialog).getByRole("heading", { name: title })).toBeVisible();
  return within(dialog);
}

export async function cancelMigrationAction(scope: Queries, button: string, title: RegExp) {
  fireEvent.click(await findMigrationButton(scope, button));
  const dialog = await migrationDialog(title);
  fireEvent.click(dialog.getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
}
