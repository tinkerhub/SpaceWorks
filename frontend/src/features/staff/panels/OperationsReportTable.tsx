import { Table, TBody, TD, TH, THead, TR } from "../../../components/ui";
import { columnLabel, formatReportCell, reportHeaders, reportRows, type ReportCell, type ReportRows } from "./OperationsReportState";

export function PerMakerspaceTables({ data, nameOf, emptyLabel = "No records." }: {
  data?: ReportRows; nameOf: (id: number) => string; emptyLabel?: string;
}) {
  if (!data?.rows?.length) return <p className="text-body-ui text-ink-muted">{emptyLabel}</p>;
  const [header, ...body] = data.rows;
  const idx = header.findIndex((cell) => cell === "makerspace_id" || cell === "makerspace");
  if (idx === -1 || !body.length) return <ReportTable data={data} />;
  const groups = new Map<string, ReportCell[][]>();
  for (const row of body) {
    const key = String(row[idx]);
    groups.set(key, [...(groups.get(key) ?? []), row]);
  }
  const subHeader = header.filter((_, index) => index !== idx);
  return (
    <div className="grid gap-5">
      {[...groups].map(([key, rows]) => (
        <div key={key}>
          <h3 className="text-label text-ink">{nameOf(Number(key))}</h3>
          <ReportTable data={{ rows: [subHeader, ...rows.map((row) => row.filter((_, index) => index !== idx))] }} />
        </div>
      ))}
    </div>
  );
}

export function ReportTable({ data, label }: { data?: ReportRows; label?: string }) {
  const headers = reportHeaders(data);
  const rows = reportRows(data);
  if (!headers.length || !rows.length) return <p className="mt-3 text-body-ui text-ink-muted">No records.</p>;
  return (
    <Table label={label} containerClassName="mt-4 max-h-80 overflow-y-auto">
      <THead className="sticky top-0 z-[1]">
        <tr>{headers.map((header) => <TH key={header}>{columnLabel(header)}</TH>)}</tr>
      </THead>
      <TBody>
        {rows.map((row, rowIndex) => (
          <TR key={rowIndex}>
            {headers.map((header, cellIndex) => (
              <TD key={`${header}-${cellIndex}`} className={`whitespace-nowrap ${typeof row[cellIndex] === "number" ? "text-right tabular-nums" : ""}`}>
                {formatReportCell(row[cellIndex])}
              </TD>
            ))}
          </TR>
        ))}
      </TBody>
    </Table>
  );
}
