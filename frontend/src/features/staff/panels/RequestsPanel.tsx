import { EmptyState } from "../../../components/ui";
import { Queues } from "./Queues";
import { type Makerspace } from "./shared";

export function RequestsPanel({ makerspace, guestOnly, canSeeHardware, canViewAudit, canReturnRequest, canReviewRequests }: {
  makerspace: Makerspace; guestOnly: boolean; canSeeHardware: boolean; canViewAudit: boolean; canReturnRequest: boolean; canReviewRequests: boolean;
}) {
  return canSeeHardware ? (
    <Queues makerspace={makerspace} guestOnly={guestOnly} canViewAudit={canViewAudit} canReturnRequest={canReturnRequest} canReviewRequests={canReviewRequests} />
  ) : (
    <EmptyState title="No hardware queues here" description="Machine-service queues are managed from Machines." />
  );
}
