import { useMutation } from "@tanstack/react-query";

import { admitUpload, type UploadGuard } from "../../../../lib/uploadProtocol";
import { useAuthActionOwner } from "../../../auth/useAuthActionOwner";

type DocumentInput = File | string | number | { guard: UploadGuard };
type Submission<T> = { input: T; guard: UploadGuard };

// Document tasks admit before TanStack can pause them. The UI's supplied guard
// still owns the full upload/retry pipeline; this adds the hook's mounted scope.
export function useMaintenanceDocumentTask<T extends DocumentInput, R>(
  scope: string,
  dispatch: (input: T) => Promise<R>,
  onSuccess?: (result: R) => void | Promise<void>,
) {
  const owner = useAuthActionOwner(scope);
  const mutation = useMutation({
    mutationFn: ({ input, guard }: Submission<T>) => {
      guard.assertCurrent();
      return dispatch(input);
    },
    onSuccess: (result, { guard }) => {
      if (guard.isCurrent()) return onSuccess?.(result);
    },
  });

  function admit(input: T): Submission<T> {
    const action = owner.capture();
    const provided = typeof input === "object" && "guard" in input ? input.guard : undefined;
    const local = admitUpload(() => owner.isCurrent(action));
    const guard: UploadGuard = {
      isCurrent: () => local.isCurrent() && (!provided || provided.isCurrent()),
      assertCurrent() {
        local.assertCurrent();
        provided?.assertCurrent();
      },
    };
    return { input, guard };
  }

  // Bounded one-argument contract: production callers use mutateAsync(input).
  // Per-call TanStack callbacks are deliberately not exposed by these wrappers.
  return {
    ...mutation,
    mutate: (input: T) => mutation.mutate(admit(input)),
    mutateAsync: (input: T) => mutation.mutateAsync(admit(input)),
  };
}
