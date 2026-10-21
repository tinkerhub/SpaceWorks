import { useEffect, useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Download } from "lucide-react";

import {
  Button,
  Chip,
  EmptyState,
  ErrorText,
  Field,
  FilterChip,
  Pagination,
  SearchInput,
  SegmentedControl,
  StatusChip,
  SwitchRow,
  Table,
  TBody,
  TD,
  THead,
  TR,
  useToast,
  type SegmentedOption,
} from "../../../components/ui";
import { downloadStaffFile } from "../../../lib/api";
import { useDebouncedValue } from "../../../lib/useDebouncedValue";
import {
  formatDate,
  isOverdue,
  ledgerParams,
  LedgerSkeleton,
  SortableHeader,
  UnitLines,
  sourceLabels,
  type LedgerResponse,
  type LedgerSourceFilter,
  type SortKey,
  type SortDirection,
} from "./LedgerParts";
import { errorText, Panel, type Makerspace, useStaffGet } from "./shared";

type SourceOption = "all" | Exclude<LedgerSourceFilter, "">;

const SOURCE_OPTIONS: ReadonlyArray<SegmentedOption<SourceOption>> = [
  { value: "all", label: "All sources" },
  { value: "reviewed", label: "Reviewed" },
  { value: "self_checkout", label: "Self-checkout" },
  { value: "direct", label: "Direct" },
];

const LEDGER_PAGE_SIZE = 50;

export function Ledger({ makerspace, isSuperadmin }: { makerspace: Makerspace; isSuperadmin: boolean }) {
  const { showToast } = useToast();
  const [allMakerspaces, setAllMakerspaces] = useState(false);
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState("");
  const [sourceFilter, setSourceFilter] = useState<LedgerSourceFilter>("");
  const [overdueOnly, setOverdueOnly] = useState(false);
  const [sort, setSort] = useState<{ key: SortKey; direction: SortDirection }>({
    key: "due",
    direction: "asc",
  });
  const debouncedFilter = useDebouncedValue(filter);
  const aggregate = isSuperadmin && allMakerspaces;
  const ledgerPath = aggregate ? "/admin/ledger" : `/admin/makerspace/${makerspace.id}/ledger`;
  const sortParam = `${sort.direction === "desc" ? "-" : ""}${sort.key}`;
  const ledgerQuery = useMemo(() => {
    const params = ledgerParams({
      page,
      pageSize: LEDGER_PAGE_SIZE,
      search: debouncedFilter,
      source: sourceFilter,
      overdueOnly,
      sort: sortParam,
    });
    return params.toString();
  }, [debouncedFilter, overdueOnly, page, sortParam, sourceFilter]);
  const exportQuery = useMemo(() => {
    const params = ledgerParams({
      search: debouncedFilter,
      source: sourceFilter,
      overdueOnly,
      sort: sortParam,
    });
    return params.toString();
  }, [debouncedFilter, overdueOnly, sortParam, sourceFilter]);
  const ledger = useStaffGet<LedgerResponse>(
    ["ledger", aggregate ? "all" : makerspace.id, ledgerQuery],
    `${ledgerPath}?${ledgerQuery}`,
  );

  useEffect(() => {
    setPage(1);
  }, [aggregate, debouncedFilter, makerspace.id, overdueOnly, sort.direction, sort.key, sourceFilter]);

  const rows = ledger.data?.results ?? [];
  const now = Date.now();
  const itemCount = rows.reduce((total, row) => total + row.quantity, 0);
  const totalRows = ledger.data?.count ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalRows / LEDGER_PAGE_SIZE));

  const setSortKey = (key: SortKey) => {
    setSort((current) => ({
      key,
      direction: current.key === key && current.direction === "asc" ? "desc" : "asc",
    }));
  };

  const exportLedger = useMutation({
    mutationFn: (format: "csv" | "xlsx") => {
      const params = new URLSearchParams(exportQuery);
      params.set("format", format);
      const filename = aggregate ? `ledger-all.${format}` : `ledger-${makerspace.slug}.${format}`;
      return downloadStaffFile(`${ledgerPath}/export?${params.toString()}`, filename);
    },
    onSuccess: (_result, format) => showToast(`Ledger exported as ${format.toUpperCase()}.`, { tone: "success" }),
    onError: (error) => showToast(errorText(error, "Could not export the ledger."), { tone: "error" }),
  });
  const filtered = Boolean(overdueOnly || filter || sourceFilter);

  return (
    <Panel
      title="Ledger"
      description="Everything that is out right now, who has it and when it is due back."
      actions={(
        <>
          <Button size="sm" startIcon={<Download />} disabled={exportLedger.isPending} onClick={() => exportLedger.mutate("csv")}>Export CSV</Button>
          <Button size="sm" startIcon={<Download />} disabled={exportLedger.isPending} onClick={() => exportLedger.mutate("xlsx")}>Export XLSX</Button>
        </>
      )}
    >
      <div className="grid gap-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-title text-ink">{itemCount} items out</p>
            <p className="text-body-ui text-ink-muted">
              {aggregate ? "Across all makerspaces" : makerspace.name}
              {ledger.data ? ` · ${ledger.data.count} records` : ""}
            </p>
          </div>
          {isSuperadmin ? (
            <SwitchRow
              label="All makerspaces"
              checked={allMakerspaces}
              onCheckedChange={(checked) => {
                setAllMakerspaces(checked);
                setPage(1);
              }}
            />
          ) : null}
        </div>

        <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
          <div className="min-w-0 flex-1">
            <Field label="Search ledger" hideLabel>
              <SearchInput placeholder="Search holder, email, item, or box" value={filter} onChange={(event) => setFilter(event.target.value)} onClear={() => setFilter("")} />
            </Field>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <SegmentedControl<SourceOption>
              ariaLabel="Source"
              size="sm"
              value={sourceFilter || "all"}
              onValueChange={(value) => setSourceFilter(value === "all" ? "" : value)}
              options={SOURCE_OPTIONS}
            />
            <FilterChip selected={overdueOnly} onClick={() => setOverdueOnly((value) => !value)}>Overdue</FilterChip>
          </div>
        </div>

        {ledger.isLoading ? <LedgerSkeleton aggregate={aggregate} /> : null}
        {ledger.error ? <ErrorText message={errorText(ledger.error, "Could not load the ledger.")} /> : null}
        {!ledger.isLoading && !ledger.error && !rows.length ? (
          <EmptyState
            title={filtered ? "Nothing matches these filters" : "No items are currently out"}
            description={filtered ? "Clear the search or filters to see everything that is out." : "Loans, self-checkouts and direct handouts show up here once they are issued."}
          />
        ) : null}

        {rows.length ? (
          <Table label="Items out" className="min-w-[760px]">
            <THead>
              <tr>
                <SortableHeader label="Item" sortKey="item_name" sort={sort} onSort={setSortKey} />
                <SortableHeader label="Holder" sortKey="holder" sort={sort} onSort={setSortKey} />
                <SortableHeader label="Qty" sortKey="quantity" sort={sort} onSort={setSortKey} align="right" />
                <SortableHeader label="Out since" sortKey="since" sort={sort} onSort={setSortKey} />
                <SortableHeader label="Due" sortKey="due" sort={sort} onSort={setSortKey} />
                <SortableHeader label="Source" sortKey="source" sort={sort} onSort={setSortKey} />
                {aggregate ? <SortableHeader label="Makerspace" sortKey="makerspace_id" sort={sort} onSort={setSortKey} /> : null}
              </tr>
            </THead>
            <TBody>
              {rows.map((row) => {
                const overdue = isOverdue(row.due, now);
                return (
                  <TR key={`${row.source}-${row.reference_id}-${row.makerspace_id}-${row.item_name}`}>
                    <TD className="align-top">
                      <div className="max-w-56 break-words font-semibold text-ink">{row.item_name}</div>
                      {row.container ? <div className="mt-0.5 break-words text-caption text-ink-muted">Box <span className="font-mono">{row.container}</span></div> : null}
                      <UnitLines row={row} />
                    </TD>
                    <TD className="align-top"><span className="block max-w-48 break-words">{row.holder}</span></TD>
                    <TD className="whitespace-nowrap text-right font-semibold tabular-nums">{row.quantity}</TD>
                    <TD className="whitespace-nowrap text-ink-muted">{formatDate(row.since)}</TD>
                    <TD className={`whitespace-nowrap ${overdue ? "font-semibold text-danger-fg" : "text-ink-muted"}`}>
                      <span className="inline-flex items-center gap-2">
                        {formatDate(row.due)}
                        {overdue ? <StatusChip tone="danger" size="sm">Overdue</StatusChip> : null}
                      </span>
                    </TD>
                    <TD className="whitespace-nowrap">
                      <Chip size="sm">{sourceLabels[row.source]}</Chip>
                    </TD>
                    {aggregate ? <TD className="whitespace-nowrap font-mono text-ink-muted">#{row.makerspace_id}</TD> : null}
                  </TR>
                );
              })}
            </TBody>
          </Table>
        ) : null}

        {ledger.data ? (
          <Pagination page={page} totalPages={totalPages} onChange={setPage} count={totalRows} pageSize={LEDGER_PAGE_SIZE} disabled={ledger.isFetching} />
        ) : null}
      </div>
    </Panel>
  );
}
