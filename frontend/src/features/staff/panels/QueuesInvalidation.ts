import type { QueryClient } from "@tanstack/react-query";
import { invalidateContainerViews, invalidateInventoryViews } from "../queryInvalidation";

export type InvalidationScope = {
  inventory: boolean;
  needsFix: boolean;
  ledger: boolean;
};

export function actionInvalidationScope(path: string): InvalidationScope {
  const inventory = path.endsWith("/accept") || path.endsWith("/issue") || path.endsWith("/return");
  const ledger = path.endsWith("/issue") || path.endsWith("/return") || path.endsWith("/return-due");
  const needsFix = path.endsWith("/issue") || path.endsWith("/return");
  return { inventory, ledger, needsFix };
}

export function invalidateRequestQueues(queryClient: QueryClient, makerspaceId: number, scope: InvalidationScope, slug?: string) {
  queryClient.invalidateQueries({ queryKey: ["pending", makerspaceId] });
  queryClient.invalidateQueries({ queryKey: ["accepted", makerspaceId] });
  queryClient.invalidateQueries({ queryKey: ["active", makerspaceId] });
  queryClient.invalidateQueries({ queryKey: ["request-history", makerspaceId] });
  // Pending-request and overdue-loan tiles count these queues; without this they lag
  // up to the 30s staleTime behind every accept/reject/issue/return.
  queryClient.invalidateQueries({ queryKey: ["dashboard", makerspaceId] });

  if (scope.inventory) {
    // The slug refreshes the public catalogue's availability as well.
    invalidateInventoryViews(queryClient, makerspaceId, slug);
    invalidateContainerViews(queryClient, makerspaceId);
  }
  if (scope.needsFix) {
    queryClient.invalidateQueries({ queryKey: ["needs-fix-shelf", makerspaceId] });
    // A return can record lost or damaged units against the borrower.
    queryClient.invalidateQueries({ queryKey: ["accountability", makerspaceId] });
  }
  if (scope.ledger) {
    queryClient.invalidateQueries({ queryKey: ["ledger", makerspaceId] });
    queryClient.invalidateQueries({ queryKey: ["ledger", "all"] });
  }
}
