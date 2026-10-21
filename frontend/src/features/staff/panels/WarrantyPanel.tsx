import { useState } from "react";

import {
  Button,
  Chip,
  Dialog,
  EmptyState,
  ErrorText,
  Field,
  FilterChip,
  Input,
  Pagination,
  SkeletonRows,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "../../../components/ui";
import { warrantyStatusLabel, WarrantyStatusBadge } from "../WarrantyStatusBadge";
import { WarrantySection } from "../WarrantySection";
import type { WarrantyHostKind, WarrantyReportRow, WarrantyStatus } from "../warrantyApi";
import { errorText, Panel, type Makerspace, useStaffGet } from "./shared";

type WarrantyResponse = {
  count: number;
  next: string | null;
  previous: string | null;
  results: WarrantyReportRow[];
};

type StatusFilter = "all" | WarrantyStatus;

const PAGE_SIZE = 50;
const STATUS_FILTERS: StatusFilter[] = ["all", "active", "expiring_soon", "expired", "unknown"];
const HEADERS = ["Host", "Vendor", "Purchased", "Expires", "Status", "Docs"];
const HOST_KIND_LABELS: Record<WarrantyHostKind, string> = { asset: "Asset", printer: "Printer", machine: "Machine" };

export function WarrantyPanel({
  makerspace,
  canEditInventory,
}: {
  makerspace: Makerspace;
  canEditInventory: boolean;
}) {
  const [status, setStatus] = useState<StatusFilter>("all");
  const [missingDocs, setMissingDocs] = useState(false);
  const [expiresBefore, setExpiresBefore] = useState("");
  const [page, setPage] = useState(1);
  const [managing, setManaging] = useState<WarrantyReportRow | null>(null);
  const canManageRow = (row: WarrantyReportRow) => {
    if (row.host_kind === "asset") return canEditInventory;
    if (row.host_kind === "printer") return false;
    return true;
  };
  const queryParams = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) });
  if (status !== "all") queryParams.set("status", status);
  if (missingDocs) queryParams.set("missing_docs", "true");
  if (expiresBefore) queryParams.set("expires_before", expiresBefore);
  const warranties = useStaffGet<WarrantyResponse>(
    ["warranties", makerspace.id, page, PAGE_SIZE, status, missingDocs, expiresBefore],
    `/admin/makerspace/${makerspace.id}/warranties?${queryParams.toString()}`,
  );

  const visibleRows = warranties.data?.results ?? [];
  const totalPages = Math.max(1, Math.ceil((warranties.data?.count ?? 0) / PAGE_SIZE));
  const filtersActive = status !== "all" || missingDocs || Boolean(expiresBefore);

  function updateStatus(value: StatusFilter) {
    setStatus(value);
    setPage(1);
  }

  function updateMissingDocs(value: boolean) {
    setMissingDocs(value);
    setPage(1);
  }

  function updateExpiresBefore(value: string) {
    setExpiresBefore(value);
    setPage(1);
  }

  function clearFilters() {
    setStatus("all");
    setMissingDocs(false);
    setExpiresBefore("");
    setPage(1);
  }

  return (
    <Panel
      title="Warranties"
      description={`Warranty coverage for equipment you can manage in ${makerspace.name}${warranties.data ? ` · ${warranties.data.count} hosts total` : ""}.`}
    >
      <div className="grid gap-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div role="group" aria-label="Status" className="flex flex-wrap items-center gap-2">
            {STATUS_FILTERS.map((value) => (
              <FilterChip key={value} selected={status === value} onClick={() => updateStatus(value)}>
                {value === "all" ? "All" : warrantyStatusLabel[value]}
              </FilterChip>
            ))}
            <FilterChip selected={missingDocs} onClick={() => updateMissingDocs(!missingDocs)}>Missing docs</FilterChip>
          </div>
          <Field label="Expires before" className="sm:w-48">
            <Input type="date" value={expiresBefore} onChange={(event) => updateExpiresBefore(event.target.value)} />
          </Field>
        </div>

        {warranties.error ? <ErrorText message={errorText(warranties.error, "Could not load warranties.")} /> : null}
        {!warranties.isLoading && !warranties.error && !visibleRows.length ? (
          <EmptyState
            title="No warranties"
            description={filtersActive ? "No hosts match these warranty filters." : "No warranty-covered hosts are in scope yet."}
            action={filtersActive ? <Button size="sm" onClick={clearFilters}>Clear filters</Button> : undefined}
          />
        ) : null}

        {warranties.isLoading || visibleRows.length ? (
          <Table label="Warranties" className="min-w-[820px]" aria-busy={warranties.isLoading || undefined}>
            <THead>
              <tr>
                {HEADERS.map((header) => <TH key={header} className={header === "Docs" ? "text-right" : undefined}>{header}</TH>)}
                <TH><span className="sr-only">Manage</span></TH>
              </tr>
            </THead>
            <TBody>
              {warranties.isLoading ? <SkeletonRows rows={4} cols={HEADERS.length + 1} /> : visibleRows.map((row) => (
                <TR key={`${row.host_kind}-${row.host_id}`}>
                  <TD className="align-top">
                    <div className="flex flex-wrap items-center gap-2">
                      <Chip size="sm">{HOST_KIND_LABELS[row.host_kind]}</Chip>
                      <span className="max-w-56 break-words font-semibold">{row.host_label}</span>
                    </div>
                    {row.serial_number ? <p className="mt-1 text-caption text-ink-muted">Serial <span className="font-mono">{row.serial_number}</span></p> : null}
                  </TD>
                  <TD className="align-top"><span className="block max-w-48 break-words">{row.vendor_name || "—"}</span></TD>
                  <TD className="whitespace-nowrap align-top text-ink-muted">{formatDate(row.purchased_on)}</TD>
                  <TD className="whitespace-nowrap align-top text-ink-muted">{formatDate(row.warranty_expires_on)}</TD>
                  <TD className="whitespace-nowrap align-top"><WarrantyStatusBadge status={row.status} /></TD>
                  <TD className="whitespace-nowrap text-right align-top tabular-nums text-ink-muted">{row.document_count}</TD>
                  <TD className="whitespace-nowrap text-right align-top">
                    {canManageRow(row) ? (
                      <Button size="sm" onClick={() => setManaging(row)}>Manage</Button>
                    ) : <span className="text-caption text-ink-muted">—</span>}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        ) : null}

        <Pagination page={page} totalPages={totalPages} onChange={setPage} count={warranties.data?.count} pageSize={PAGE_SIZE} disabled={warranties.isFetching} />
      </div>
      <Dialog
        open={managing !== null && canManageRow(managing)}
        onClose={() => setManaging(null)}
        title={managing?.host_label ?? "Warranty"}
        description={managing ? `${HOST_KIND_LABELS[managing.host_kind]}${managing.serial_number ? ` · serial ${managing.serial_number}` : ""}` : undefined}
        size="lg"
        footer={<div className="flex justify-end"><Button onClick={() => setManaging(null)}>Done</Button></div>}
      >
        {managing ? <WarrantySection hostKind={managing.host_kind} hostId={managing.host_id} /> : null}
      </Dialog>
    </Panel>
  );
}

function formatDate(value: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}
