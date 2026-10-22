import { useState } from "react";

import { Button, EmptyState, ErrorText, SectionHeading, SkeletonRows, Table, TBody, TD, TH, THead, TR, useToast } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { evidenceErrorText } from "./evidenceUi";
import { StatusWord } from "./panels/shared";

export type DirectLoan = {
  id: number;
  public_token: string;
  status: string;
  target_label: string;
  container_label?: string | null;
  due_at: string | null;
  issued_by: { username: string; role: string } | null;
  // The person holding the tools (snapshot at issue); optional for older cached payloads.
  borrower_name?: string;
  issue_evidence_id?: number | null;
  return_evidence_id?: number | null;
  return_notes?: string;
  return_scan_required?: boolean;
  items: { product_name: string; quantity: number }[];
  return_items?: DirectLoanReturnItem[];
};

export type DirectLoanReturnItem = {
  item_id: number;
  product_name: string;
  remaining_quantity: number;
  tracking_mode: string;
  assets: { asset_id: number; asset_tag: string }[];
};

const dateTime = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

export function DirectLoanList({
  loans,
  loading = false,
  error = null,
  onReturn,
}: {
  loans: DirectLoan[];
  loading?: boolean;
  error?: Error | null;
  onReturn: (loan: DirectLoan) => void;
}) {
  const { showToast } = useToast();
  const [evidenceError, setEvidenceError] = useState<{ loanId: number; message: string } | null>(null);
  const openEvidence = async (loanId: number, evidenceId: number) => {
    setEvidenceError(null);
    try {
      const res = await staffRequest<{ url: string }>(`/admin/evidence/${evidenceId}`);
      window.open(res.url, "_blank", "noopener");
    } catch (failure) {
      const message = evidenceErrorText(failure);
      setEvidenceError({ loanId, message });
      showToast(message, { tone: "error" });
    }
  };

  return (
    <section className="grid gap-3">
      <SectionHeading title="Handout loans" description="Tools lent from the desk. Return them here when they come back." />
      <ErrorText message={error?.message} />
      {!loading && !loans.length ? (
        <EmptyState title="No handouts yet" description="Issue a handout above and it will show up here until it's returned." />
      ) : (
        <Table label="Handout loans" className="min-w-[840px]" aria-busy={loading}>
          <THead>
            <tr>
              <TH>Handout</TH>
              <TH>Borrower</TH>
              <TH>Status</TH>
              <TH>Due</TH>
              <TH>Issued by</TH>
              <TH>Photos</TH>
              <TH><span className="sr-only">Actions</span></TH>
            </tr>
          </THead>
          <TBody>
            {loading ? <SkeletonRows rows={4} cols={7} /> : loans.map((loan) => {
              const returned = loan.status !== "checked_out";
              return (
                <TR key={loan.id}>
                  <TD className="min-w-56">
                    <p className="font-semibold text-ink">{loan.target_label}</p>
                    <p className="mt-0.5 text-caption text-ink-muted">
                      {loan.items.map((item) => `${item.product_name} ×${item.quantity}`).join(", ")}
                      {loan.container_label ? `${loan.items.length ? " · " : ""}Given in ${loan.container_label}` : ""}
                    </p>
                    {returned && loan.return_notes ? <p className="mt-1 text-caption text-ink-secondary">Return notes: {loan.return_notes}</p> : null}
                    {evidenceError?.loanId === loan.id ? <p className="mt-1 text-caption text-danger-fg" role="alert">{evidenceError.message}</p> : null}
                  </TD>
                  <TD className="min-w-32 text-ink [overflow-wrap:anywhere]">{loan.borrower_name || "—"}</TD>
                  <TD>
                    <StatusWord status={loan.status} label={directLoanStatusLabel(loan.status)} tone={loan.status === "checked_out" ? "info" : loan.status === "returned" ? "success" : undefined} />
                  </TD>
                  <TD className="whitespace-nowrap text-ink-secondary">{loan.due_at ? dateTime.format(new Date(loan.due_at)) : "No due date"}</TD>
                  <TD className="text-ink-secondary">{loan.issued_by?.username ?? "—"}</TD>
                  <TD>
                    <div className="flex flex-wrap gap-x-3">
                      {loan.issue_evidence_id ? (
                        <Button variant="quiet" size="sm" onClick={() => void openEvidence(loan.id, loan.issue_evidence_id as number)}>View issue photo</Button>
                      ) : null}
                      {returned && loan.return_evidence_id ? (
                        <Button variant="quiet" size="sm" onClick={() => void openEvidence(loan.id, loan.return_evidence_id as number)}>View return photo</Button>
                      ) : null}
                      {!loan.issue_evidence_id && !(returned && loan.return_evidence_id) ? <span className="text-ink-muted">—</span> : null}
                    </div>
                  </TD>
                  <TD className="text-right">
                    {loan.status === "checked_out" ? <Button size="sm" onClick={() => onReturn(loan)}>Return</Button> : null}
                  </TD>
                </TR>
              );
            })}
          </TBody>
        </Table>
      )}
    </section>
  );
}

function directLoanStatusLabel(status: string) {
  switch (status) {
    case "checked_out":
      return "Lent";
    case "returned":
      return "Returned";
    default: {
      const words = status.replace(/_/g, " ");
      return words.charAt(0).toUpperCase() + words.slice(1);
    }
  }
}
