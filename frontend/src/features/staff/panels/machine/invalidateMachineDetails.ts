import type { Query, QueryClient } from "@tanstack/react-query";

import { machineKeys } from "../../machinesApi";

export async function invalidateMachineDetails(queryClient: QueryClient, isCurrent: () => boolean) {
  if (!isCurrent()) return;
  const predicate = ({ queryKey }: Query) => queryKey.length === 2 &&
    typeof queryKey[1] === "number" &&
    machineKeys.detail(queryKey[1]).every((part, index) => part === queryKey[index]);
  // Cancel initial reads too: a pre-transition response must not restore stale details.
  await queryClient.cancelQueries({ predicate });
  if (!isCurrent()) return;
  void queryClient.invalidateQueries({ predicate });
}
