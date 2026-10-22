import { Table, TBody, TD, TH, THead, TR } from "../../../components/ui";
import { BarChart, DataState, ReportCard, ScopeGroup } from "./OperationsReportsParts";
import { useStaffGet } from "./shared";

type PaymentReportRow = {
  makerspace_id?: number;
  currency: string;
  subject_type: string;
  status: string;
  payment_count: number;
  amount_total: string;
  outstanding_amount: string;
};

type PaymentReport = { typed_rows: PaymentReportRow[] };

export function OperationsReportsPayments({ analyticsBase, scopeKey, startDate, endDate, enabled, makerspaceName }: {
  analyticsBase: string; scopeKey: number | "all"; startDate: string; endDate: string;
  enabled: boolean; makerspaceName: (id: number) => string;
}) {
  const query = new URLSearchParams();
  if (startDate) query.set("start", startDate);
  if (endDate) query.set("end", endDate);
  const report = useStaffGet<PaymentReport>(
    ["operations-report", "payment-reconciliation", scopeKey, startDate, endDate],
    `${analyticsBase}/payment-reconciliation?${query.toString()}`,
    enabled,
  );
  const rows = report.data?.typed_rows ?? [];

  return (
    <ReportCard title="Payment reconciliation" description="Private totals grouped by makerspace, currency, subject and status. Pending payments stay visible whatever the dates.">
      <DataState loading={report.isLoading} error={report.error} empty={!rows.length}>
        {scopeKey === "all" ? (
          <div className="grid gap-6">
            {paymentGroups(rows).map(([makerspaceId, group]) => (
              <ScopeGroup key={makerspaceId} name={makerspaceName(makerspaceId)}>
                <PaymentChart rows={group} />
                <PaymentTable rows={group} />
              </ScopeGroup>
            ))}
          </div>
        ) : <><PaymentChart rows={rows} /><PaymentTable rows={rows} /></>}
      </DataState>
    </ReportCard>
  );
}

function PaymentChart({ rows }: { rows: PaymentReportRow[] }) {
  return <div className="grid gap-5">{currencyGroups(rows).map(([currency, group]) => (
    <section key={currency}>
      <h3 className="text-label text-ink">{currency.toUpperCase()}</h3>
      <div className="mt-2 grid gap-5 lg:grid-cols-2">
        <BarChart rows={group.map((row) => ({ label: label(row.status), value: row.payment_count }))} valueLabel="payments" />
        <BarChart rows={group.map((row) => ({ label: label(row.status), value: Number(row.amount_total) }))} valueLabel={`${currency.toUpperCase()} total`} />
      </div>
    </section>
  ))}</div>;
}

function PaymentTable({ rows }: { rows: PaymentReportRow[] }) {
  return (
    <Table containerClassName="mt-4">
      <THead><tr>
        <TH>Currency</TH><TH>Subject</TH><TH>Status</TH>
        <TH className="text-right">Payments</TH><TH className="text-right">Total</TH><TH className="text-right">Outstanding</TH>
      </tr></THead>
      <TBody>{rows.map((row, index) => (
        <TR key={`${row.currency}-${row.subject_type}-${row.status}-${index}`}>
          <TD>{row.currency.toUpperCase()}</TD>
          <TD>{label(row.subject_type)}</TD>
          <TD>{label(row.status)}</TD>
          <TD className="text-right tabular-nums">{row.payment_count}</TD>
          <TD className="text-right tabular-nums">{money(row.amount_total, row.currency)}</TD>
          <TD className="text-right font-semibold tabular-nums">{money(row.outstanding_amount, row.currency)}</TD>
        </TR>
      ))}</TBody>
    </Table>
  );
}

function paymentGroups(rows: PaymentReportRow[]) {
  const groups = new Map<number, PaymentReportRow[]>();
  for (const row of rows) {
    if (row.makerspace_id === undefined) continue;
    groups.set(row.makerspace_id, [...(groups.get(row.makerspace_id) ?? []), row]);
  }
  return [...groups];
}

function currencyGroups(rows: PaymentReportRow[]) {
  const groups = new Map<string, PaymentReportRow[]>();
  for (const row of rows) groups.set(row.currency, [...(groups.get(row.currency) ?? []), row]);
  return [...groups];
}

function label(value: string) {
  return value.replace(/_/g, " ").replace(/^./, (letter) => letter.toUpperCase());
}

function money(amount: string, currency: string) {
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency: currency.toUpperCase() }).format(Number(amount));
  } catch {
    return `${currency.toUpperCase()} ${amount}`;
  }
}
