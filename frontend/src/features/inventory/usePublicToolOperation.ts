import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useToast } from "../../components/ui";
import type { PublicToolCheckout, PublicToolScan } from "../../generated/api";
import type { PublicToolLoan } from "../../types/inventory";
import type { AuthAction, useAuthActionOwner } from "../auth/useAuthActionOwner";
import { invalidatePublicInventory } from "../staff/queryInvalidation";
import { publicToolCheckout, publicToolReturn } from "./api";

export type ToolOperation =
  | { operation: "checkout"; body: PublicToolCheckout }
  | { operation: "return"; body: PublicToolScan };
type Input = ToolOperation & { slug: string; action: AuthAction };
type View = { action: AuthAction; pending: boolean; error?: string; result?: PublicToolLoan };

/** One admission owner and one publication surface for the two competing loan operations. */
export function usePublicToolOperation(
  slug: string,
  owner: ReturnType<typeof useAuthActionOwner>,
  onSuccess: (input: ToolOperation) => void,
) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [stored, setView] = useState<View | null>(null);
  const view = stored && owner.isCurrent(stored.action) ? stored : null;
  const mutation = useMutation({
    mutationFn: (input: Input) => {
      if (!owner.isCurrent(input.action)) throw new Error("Tool operation context changed.");
      return input.operation === "checkout"
        ? publicToolCheckout(input.slug, input.body)
        : publicToolReturn(input.slug, input.body);
    },
    onSuccess: (result, input) => {
      if (!owner.isCurrent(input.action)) return;
      setView({ action: input.action, pending: true, result });
      invalidatePublicInventory(queryClient, input.slug);
      onSuccess(input);
      showToast(input.operation === "checkout" ? "Tool checked out" : "Tool returned", { tone: "success" });
    },
    onError: (error, input) => {
      if (!owner.isCurrent(input.action)) return;
      setView({ action: input.action, pending: true, error: error.message });
      showToast(input.operation === "checkout" ? "Checkout failed" : "Return failed", { tone: "error" });
    },
    onSettled: (_result, _error, input) => {
      if (!owner.isCurrent(input.action)) return;
      setView((current) => current?.action === input.action ? { ...current, pending: false } : current);
      owner.finish(input.action);
    },
  });

  function submit(operation: ToolOperation) {
    const action = owner.begin();
    if (!action) return;
    // Copy arrays too: the admitted body must never follow later scan/selection edits.
    const input: Input = operation.operation === "checkout"
      ? { operation: "checkout", body: { ...operation.body, ...(operation.body.qr_payloads ? { qr_payloads: [...operation.body.qr_payloads] } : {}) }, slug, action }
      : { operation: "return", body: { ...operation.body }, slug, action };
    setView({ action, pending: true });
    mutation.mutate(input);
  }

  return { submit, pending: view?.pending ?? false, error: view?.error, result: view?.result };
}
