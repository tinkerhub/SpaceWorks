import { useEffect, useMemo, useState } from "react";
import { Plus } from "lucide-react";

import { Button, Callout, Pagination } from "../../../components/ui";
import { usePaginatedQuery } from "../../../lib/usePaginatedQuery";
import { Panel, type Makerspace, useStaffGet } from "./shared";
import { TransferTable } from "./StockTransferTable";
import { labelForContainer, NewTransferDialog, type Container } from "./StockTransferForm";

type ListResponse<T> = { count?: number; results: T[] };
type TransferLine = { id: number; product: number | null; asset: number | null; quantity: number };
export type Transfer = {
  id: number;
  makerspace: number;
  source_container: number | null;
  destination_container: number | null;
  source_makerspace: number | null;
  destination_makerspace: number | null;
  reason: string;
  status: string;
  created_at: string;
  lines: TransferLine[];
};

export function StockTransferPanel({
  makerspace,
  makerspaces,
  isSuperadmin,
  canEditInventory = false,
}: {
  makerspace: Makerspace;
  makerspaces: Makerspace[];
  isSuperadmin: boolean;
  canEditInventory?: boolean;
}) {
  // EDIT_INVENTORY holders can run INTRA-makerspace relocations; only a superadmin gets the
  // source/destination makerspace selectors (cross-makerspace moves are superadmin-only).
  const canCreate = isSuperadmin || canEditInventory;
  const spaceOptions = useMemo(() => (makerspaces.length ? makerspaces : [makerspace]), [makerspaces, makerspace]);
  const [sourceMakerspaceId, setSourceMakerspaceId] = useState(makerspace.id);
  const [destinationMakerspaceId, setDestinationMakerspaceId] = useState(makerspace.id);
  const [formOpen, setFormOpen] = useState(false);

  useEffect(() => {
    setSourceMakerspaceId(makerspace.id);
    setDestinationMakerspaceId(makerspace.id);
    setFormOpen(false);
  }, [makerspace.id]);

  const transfers = usePaginatedQuery<Transfer>({
    key: ["transfers", sourceMakerspaceId],
    path: `/admin/makerspace/${sourceMakerspaceId}/stock-transfers`,
    resetKey: String(sourceMakerspaceId),
  });
  // Same query keys as the dialog's pickers, so the names below share its cache.
  const sourceContainers = useStaffGet<ListResponse<Container>>(
    ["containers", sourceMakerspaceId],
    `/admin/makerspace/${sourceMakerspaceId}/containers?page_size=1000`,
    canCreate,
  );
  const destinationContainers = useStaffGet<ListResponse<Container>>(
    ["containers", destinationMakerspaceId],
    `/admin/makerspace/${destinationMakerspaceId}/containers?page_size=1000`,
    canCreate,
  );

  const makerspaceNames = useMemo(() => new Map(spaceOptions.map((space) => [space.id, space.name])), [spaceOptions]);
  const sourceContainerNames = useMemo(
    () => new Map((sourceContainers.data?.results ?? []).map((box) => [box.id, labelForContainer(box)])),
    [sourceContainers.data?.results],
  );
  const destinationContainerNames = useMemo(
    () => new Map((destinationContainers.data?.results ?? []).map((box) => [box.id, labelForContainer(box)])),
    [destinationContainers.data?.results],
  );

  return (
    <Panel
      title="Stock transfers"
      description={isSuperadmin ? "Move stock between containers or between makerspaces." : "Move stock between containers in this makerspace."}
      actions={canCreate ? <Button variant="primary" startIcon={<Plus />} onClick={() => setFormOpen(true)}>New transfer</Button> : null}
    >
      <div className="grid gap-4">
        {!canCreate ? (
          <Callout tone="info" title="View only">Transfers are managed by inventory staff.</Callout>
        ) : null}
        <TransferTable
          transfers={transfers.results}
          loading={transfers.isLoading}
          error={transfers.error?.message}
          makerspaceNames={makerspaceNames}
          sourceContainerNames={sourceContainerNames}
          destinationContainerNames={destinationContainerNames}
          onCreate={canCreate ? () => setFormOpen(true) : undefined}
        />
        <Pagination page={transfers.page} totalPages={transfers.totalPages} onChange={transfers.setPage} count={transfers.count} pageSize={transfers.pageSize} />
      </div>
      {canCreate ? (
        <NewTransferDialog
          open={formOpen}
          onClose={() => setFormOpen(false)}
          isSuperadmin={isSuperadmin}
          spaceOptions={spaceOptions}
          sourceMakerspaceId={sourceMakerspaceId}
          destinationMakerspaceId={destinationMakerspaceId}
          onSourceChange={(nextId) => {
            setSourceMakerspaceId(nextId);
            setDestinationMakerspaceId(nextId);
          }}
          onDestinationChange={setDestinationMakerspaceId}
        />
      ) : null}
    </Panel>
  );
}
