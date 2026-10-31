import { StrictMode } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, vi } from "vitest";

import { CheckinIdentityStep } from "../features/inventory/CheckinIdentityStep";
import { RegressionProviders, regressionClient, rosterMatch } from "./uiRegressionHarness";

export function renderCheckin(strict = false) {
  const client = regressionClient();
  const onConfirm = vi.fn();
  const tree = (slug: string, disabled: boolean) => {
    const step = <RegressionProviders client={client}>
      <CheckinIdentityStep makerspaceSlug={slug} confirmed={null} onConfirm={onConfirm} disabled={disabled} />
    </RegressionProviders>;
    return strict ? <StrictMode>{step}</StrictMode> : step;
  };
  const view = render(tree("a", false));
  return { ...view, client, onConfirm, changeContext: (slug: string, disabled = false) => view.rerender(tree(slug, disabled)) };
}

export function startLookup(name = "ada typed") {
  fireEvent.change(screen.getByLabelText(/your name/i), { target: { value: name } });
  fireEvent.click(screen.getByRole("button", { name: "Find me" }));
}

export function nonNullConfirmations(onConfirm: ReturnType<typeof vi.fn>) {
  return onConfirm.mock.calls.filter(([match]) => match !== null);
}

export async function settleLookup(pending: { resolve: (matches: (typeof rosterMatch)[]) => void }, matches = [rosterMatch]) {
  await act(async () => { pending.resolve(matches); });
  await waitFor(() => expect(screen.getByLabelText(/your name/i)).toBeEnabled());
}
