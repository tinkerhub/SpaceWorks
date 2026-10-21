import { Button, EmptyState, ErrorText, SkeletonRows, Table, TBody, TD, TH, THead, TR } from "../../../components/ui";
import { StatusWord } from "./shared";
import type { Transfer } from "./StockTransferPanel";

const COLUMNS = ["ID", "Status", "Source", "Destination", "Reason", "Created", "Lines"];

export function TransferTable({
  transfers,
  loading,
  error,
  makerspaceNames,
  sourceContainerNames,
  destinationContainerNames,
  onCreate,
}: {
  transfers: Transfer[];
  loading: boolean;
  error?: string;
  makerspaceNames: Map<number, string>;
  sourceContainerNames: Map<number, string>;
  destinationContainerNames: Map<number, string>;
  onCreate?: () => void;
}) {
  if (error) return <ErrorText message={error} />;
  if (!loading && !transfers.length) {
    return (
      <EmptyState
        title="No stock transfers yet"
        description="Transfers you create show up here with where the stock came from and went."
        action={onCreate ? <Button onClick={onCreate}>New transfer</Button> : undefined}
      />
    );
  }
  return (
    <Table label="Stock transfers" className="min-w-[760px]" aria-busy={loading}>
      <THead>
        <tr>{COLUMNS.map((column) => <TH key={column}>{column}</TH>)}</tr>
      </THead>
      <TBody>
        {loading ? <SkeletonRows rows={4} cols={COLUMNS.length} /> : transfers.map((transfer) => (
          <TR key={transfer.id}>
            <TD className="whitespace-nowrap font-mono">#{transfer.id}</TD>
            <TD>{transfer.status ? <StatusWord status={transfer.status} /> : "-"}</TD>
            <TD><span className="block max-w-56 break-words">{endpointLabel(transfer.source_makerspace ?? transfer.makerspace, transfer.source_container, makerspaceNames, sourceContainerNames)}</span></TD>
            <TD><span className="block max-w-56 break-words">{endpointLabel(transfer.destination_makerspace ?? transfer.makerspace, transfer.destination_container, makerspaceNames, destinationContainerNames)}</span></TD>
            <TD className="min-w-48 text-ink-secondary"><span className="block max-w-64 break-words">{transfer.reason}</span></TD>
            <TD className="whitespace-nowrap text-ink-muted">{formatDate(transfer.created_at)}</TD>
            <TD className="whitespace-nowrap tabular-nums">{transfer.lines.length}</TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}

function endpointLabel(spaceId: number, containerId: number | null, spaceNames: Map<number, string>, containerNames: Map<number, string>) {
  const space = spaceNames.get(spaceId) ?? `Makerspace #${spaceId}`;
  return containerId ? `${space} / ${containerNames.get(containerId) ?? `Container #${containerId}`}` : space;
}

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
