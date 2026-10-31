import { useMutation } from "@tanstack/react-query";
import { useAuthActionOwner, type AuthAction } from "../../../auth/useAuthActionOwner";

type Submission<T> = { action: AuthAction; input: T };

// Queue and manual usage call this separately: their pending ownership is independent.
export function useServiceOperation<T>(scope: string, options: {
  dispatch: (input: T) => Promise<unknown>;
  success: (input: T, isCurrent: () => boolean) => void;
  failure: (error: Error, input: T) => void;
}) {
  const owner = useAuthActionOwner(scope);
  const mutation = useMutation({
    mutationFn: ({ action, input }: Submission<T>) => {
      if (!owner.isCurrent(action)) throw new Error("This service action is no longer current.");
      return options.dispatch(input);
    },
    onSuccess: (_result, { action, input }) => {
      if (owner.isCurrent(action)) options.success(input, () => owner.isCurrent(action));
    },
    onError: (error, { action, input }) => {
      if (owner.isCurrent(action)) options.failure(error, input);
    },
    onSettled: (_result, _error, { action }) => { owner.finish(action); },
  });
  const current = owner.isCurrent(mutation.variables?.action ?? null);
  return {
    error: current ? mutation.error : null,
    pending: current && mutation.isPending,
    canEdit: () => owner.isIntentCurrent() && !owner.isPending(),
    submit(input: T) {
      if (!owner.isIntentCurrent()) return;
      const action = owner.begin();
      if (action) mutation.mutate({ action, input });
    },
  };
}
