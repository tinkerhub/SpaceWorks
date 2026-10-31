import { act, fireEvent, render, screen } from "@testing-library/react";
import { useLayoutEffect } from "react";
import { MemoryRouter, useLocation, useNavigate } from "react-router-dom";
import { expect } from "vitest";

import { ResetPasswordPage } from "../features/staff/ResetPasswordPage";

export const RECOVERY_PASSWORD = "New-password-419!";

export function heldRecovery() {
  let resolve!: (value: unknown) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<unknown>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

export async function settleRecovery(
  held: ReturnType<typeof heldRecovery>, outcome: "resolve" | "reject", detail = "Current acknowledgement",
) {
  await act(async () => {
    if (outcome === "resolve") held.resolve({ detail });
    else held.reject(new Error("Obsolete transport failure"));
  });
}

export function enterRecovery(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

export function fillRecoveryPassword() {
  enterRecovery("New password", RECOVERY_PASSWORD);
  enterRecovery("Confirm password", RECOVERY_PASSWORD);
}

export function submitRecovery(name: string) {
  fireEvent.submit(screen.getByRole("form", { name }));
}

// Reads at the navigation commit, before passive effects could scrub stale state.
export function recoverySnapshot() {
  return {
    secrets: ["New password", "Confirm password"].map((label) =>
      (screen.queryByLabelText(label) as HTMLInputElement | null)?.value ?? null),
    updated: Boolean(screen.queryByRole("heading", { name: "Password updated" })),
    error: screen.queryByRole("alert")?.textContent ?? null,
  };
}

export function mountRecoveryRoutes(
  routes: Record<string, string>, onCommit?: (route: string) => void,
) {
  function Visits() {
    const navigate = useNavigate();
    const location = useLocation();
    const route = `${location.pathname}${location.search}`;
    useLayoutEffect(() => { onCommit?.(route); }, [location.key]);
    return <>
      <output aria-label="Committed recovery route">{route}</output>
      {Object.entries(routes).map(([name, path]) =>
        <button key={name} onClick={() => navigate(path)}>Visit {name}</button>)}
    </>;
  }
  const view = render(<MemoryRouter initialEntries={[Object.values(routes)[0]]} useTransitions={false}>
    <ResetPasswordPage /><Visits />
  </MemoryRouter>);
  return { ...view, visit(name: string) {
    fireEvent.click(screen.getByRole("button", { name: `Visit ${name}` }));
    // Separate calls prove B committed before a later visit returns to A.
    expect(screen.getByLabelText("Committed recovery route").textContent).toBe(routes[name]);
  } };
}
