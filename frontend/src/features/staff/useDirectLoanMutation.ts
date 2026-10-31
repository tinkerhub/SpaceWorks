import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useToast } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { useAuthActionOwner, type AuthAction } from "../auth/useAuthActionOwner";
import { errorText, type Makerspace } from "./panels/shared";
import { invalidateContainerViews, invalidateInventoryViews } from "./queryInvalidation";

type LoanCommand = { owner: AuthAction; path: string; body: string; makerId: number; slug: string };

// Direct issue and return share cache effects, but retain separate form visits and pending locks.
export function useDirectLoanMutation(scope: string, makerspace: Makerspace, done: string, failed: string, reset: () => void) {
  const owner = useAuthActionOwner(scope);
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const mutation = useMutation({
    mutationFn: (request: LoanCommand) => {
      if (!owner.isCurrent(request.owner)) throw new Error("Handout visit changed.");
      return staffRequest(request.path, { method: "POST", body: request.body });
    },
    onSuccess: (_data, request) => {
      if (!owner.isCurrent(request.owner)) return;
      for (const key of ["direct-loans", "accountability", "needs-fix-shelf", "active", "dashboard"]) {
        queryClient.invalidateQueries({ queryKey: [key, request.makerId] });
      }
      invalidateInventoryViews(queryClient, request.makerId, request.slug);
      invalidateContainerViews(queryClient, request.makerId);
      owner.cancel();
      reset();
      showToast(done, { tone: "success" });
    },
    onError: (failure, request) => {
      if (owner.isCurrent(request.owner)) showToast(errorText(failure, failed), { tone: "error" });
    },
    onSettled: (_data, _error, request) => { owner.finish(request.owner); },
  });
  const editable = () => owner.isIntentCurrent() && !owner.isPending();
  function submit(path: string, body: object) {
    if (!editable()) return;
    const token = owner.begin();
    if (!token) return;
    mutation.mutate({ owner: token, path, body: JSON.stringify(body), makerId: makerspace.id, slug: makerspace.slug });
  }
  function cancel() { owner.cancel(); mutation.reset(); }
  return {
    submit, cancel, editable,
    isPending: mutation.isPending && owner.isPending(),
    error: mutation.variables && owner.isCurrent(mutation.variables.owner) ? mutation.error : null,
  };
}
