import { useState } from "react";

import { Button, Card, CardHeader, ErrorText, Field, Pagination, Textarea } from "../../components/ui";
import { getSessionGeneration } from "../../lib/apiSession";
import { useDirectLoanMutation } from "./useDirectLoanMutation";
import { usePaginatedQuery } from "../../lib/usePaginatedQuery";
import { DirectLoanBorrower } from "./DirectLoanBorrower";
import { DirectLoanItems } from "./DirectLoanItems";
import { DirectLoanList, type DirectLoan } from "./DirectLoanList";
import { DirectLoanReturnModal, type DirectLoanResolution } from "./DirectLoanReturnModal";
import {
  DEFAULT_ISSUE_REMARK,
  FIRST_LINE,
  listResults,
  type ContainerResponse,
  type DirectLoanMemberResponse,
  type LineDraft,
  type ProductOption,
  type ScannedPayload,
} from "./DirectLoanTypes";
import { MemberClaimCodes } from "./MemberClaimCodes";
import { moduleEnabled } from "../../lib/modules";
import { EvidenceUpload } from "./panels/EvidenceUpload";
import { Panel, type Makerspace, useStaffGet } from "./panels/shared";

export function DirectLoans({ makerspace }: { makerspace: Makerspace }) {
  return <DirectLoanVisit key={`${makerspace.id}:${getSessionGeneration()}`} makerspace={makerspace} />;
}

function DirectLoanVisit({ makerspace }: { makerspace: Makerspace }) {
  const [borrowerId, setBorrowerId] = useState("");
  const [lineRows, setLineRows] = useState<LineDraft[]>([FIRST_LINE]);
  const [scanned, setScanned] = useState<ScannedPayload[]>([]);
  const [qrPayloads, setQrPayloads] = useState("");
  const [containerId, setContainerId] = useState("");
  const [issueEvidenceId, setIssueEvidenceId] = useState<number | null>(null);
  const [issueRemark, setIssueRemark] = useState(DEFAULT_ISSUE_REMARK);
  // Bumped to remount the photo upload and item picker (clearing their local state).
  const [formKey, setFormKey] = useState(0);
  const [returnVisit, setReturnVisit] = useState(0);
  const [returningLoan, setReturningLoan] = useState<DirectLoan | null>(null);
  const [returnEvidenceId, setReturnEvidenceId] = useState<number | null>(null);
  const [returnNotes, setReturnNotes] = useState("");
  const [returnQrPayload, setReturnQrPayload] = useState("");

  const resetIssueForm = () => {
    setLineRows([FIRST_LINE]);
    setScanned([]);
    setQrPayloads("");
    setContainerId("");
    setIssueEvidenceId(null);
    setIssueRemark(DEFAULT_ISSUE_REMARK);
    setFormKey((key) => key + 1);
  };
  const resetReturnState = () => {
    setReturningLoan(null);
    setReturnEvidenceId(null);
    setReturnNotes("");
    setReturnQrPayload("");
  };
  const products = useStaffGet<{ results: ProductOption[] }>(["inventory-all", makerspace.id], `/admin/makerspace/${makerspace.id}/inventory?page_size=1000`);
  // Fetch ALL containers (distinct cache key from the shared ["containers"] entry so a
  // truncated first page can't leak in): the dropdown + the scan membership check both
  // need the complete list, else a valid container past page one falsely reads as "not found".
  // The `containers` module guards that endpoint: without it there is nothing to pick.
  const containersOn = moduleEnabled(makerspace.enabled_modules, "containers");
  const containers = useStaffGet<ContainerResponse>(["containers-all", makerspace.id], `/admin/makerspace/${makerspace.id}/containers?page_size=1000`, containersOn);
  // A DRF ListAPIView answers with the paginated envelope, not a bare array; listResults
  // unwraps both, so `.map` can never take the whole panel down.
  const members = useStaffGet<DirectLoanMemberResponse>(["direct-loan-members", makerspace.id], `/admin/makerspace/${makerspace.id}/direct-loan-members?page_size=1000`);
  const memberOptions = listResults(members.data);
  const containerOptions = listResults(containers.data);
  const activeProducts = (products.data?.results ?? []).filter((product) => !product.is_archived);
  const productById = new Map(activeProducts.map((product) => [product.id, product]));
  const loans = usePaginatedQuery<DirectLoan>({
    key: ["direct-loans", makerspace.id],
    path: `/admin/makerspace/${makerspace.id}/direct-loans`,
    resetKey: String(makerspace.id),
  });

  const pastedQrPayloads = qrPayloads.split("\n").map((value) => value.trim()).filter(Boolean);
  const validManualLines = lineRows.filter((line) => {
    const product = productById.get(Number(line.productId));
    return Boolean(product) && product?.tracking_mode !== "individual" && Number(line.quantity) > 0;
  });
  const hasIssueContent = validManualLines.length > 0 || scanned.length > 0 || pastedQrPayloads.length > 0 || Boolean(containerId);

  const issue = useDirectLoanMutation(`issue:${makerspace.id}:${formKey}`, makerspace, "Handout issued.", "Could not issue the handout.", resetIssueForm);
  const returnLoan = useDirectLoanMutation(`return:${makerspace.id}:${returningLoan?.id}:${returnVisit}`, makerspace, "Return recorded.", "Could not record the return.", resetReturnState);
  const submitIssue = () => {
    if (!canIssue || !issue.editable()) return;
    issue.submit(`/admin/makerspace/${makerspace.id}/direct-loans`, {
      borrower_id: Number(borrowerId), evidence_id: issueEvidenceId, remark: issueRemark.trim(),
      container_id: containerId ? Number(containerId) : null,
      qr_payloads: Array.from(new Set([...scanned.map((item) => item.payload), ...pastedQrPayloads])),
      items: validManualLines.map((line) => ({ product_id: Number(line.productId), quantity: Number(line.quantity) })),
    });
  };
  const canIssue = Boolean(borrowerId) && hasIssueContent && issueEvidenceId !== null && !issue.isPending;

  const openReturnModal = (loan: DirectLoan) => {
    if (!returnLoan.editable()) return;
    returnLoan.cancel();
    setReturnVisit((value) => value + 1);
    resetReturnState();
    setReturningLoan(loan);
  };
  const closeReturnModal = () => {
    if (!returnLoan.editable()) return;
    returnLoan.cancel();
    setReturnVisit((value) => value + 1);
    resetReturnState();
  };
  const submitReturn = (resolutions: DirectLoanResolution[]) => {
    if (!returnLoan.editable() || !returningLoan || returnEvidenceId === null || !returnNotes.trim()) return;
    if (returningLoan.return_scan_required && !returnQrPayload.trim()) return;
    returnLoan.submit(`/admin/direct-loans/${returningLoan.id}/return`, {
      evidence_id: returnEvidenceId, notes: returnNotes.trim(), qr_payload: returnQrPayload.trim(), resolutions,
    });
  };
  // Waivers and the member wording belong to `membership`; claim codes redeem into a member
  // sign-in, so they need `member_accounts`. Neither may show on a space without them.
  const membershipOn = moduleEnabled(makerspace.enabled_modules, "membership");
  const claimCodesOn = moduleEnabled(makerspace.enabled_modules, "member_accounts");
  const missing = [
    !borrowerId ? (membershipOn ? "choose the borrowing member" : "choose the borrower") : null,
    !hasIssueContent ? `add at least one item${containersOn ? ", QR code or container" : " or QR code"}` : null,
    issueEvidenceId === null ? "upload an issue photo" : null,
  ].filter(Boolean);

  return (
    <Panel title="Direct handout" description={`Lend tools to ${membershipOn ? "a member" : "someone"} at the desk, with a photo of what went out.`}>
      <div className="grid gap-8">
        <Card as="section" padding="lg" className="grid gap-6">
          <CardHeader className="mb-0" title="New handout" description={`Every handout needs ${membershipOn ? "a member" : "a borrower"}, what's going out and an issue photo.`} />
          <DirectLoanBorrower
            key={formKey}
            disabled={issue.isPending}
            canEdit={issue.editable}
            makerspaceId={makerspace.id}
            members={memberOptions}
            loading={members.isLoading}
            error={members.error}
            borrowerId={borrowerId}
            onBorrowerChange={(id) => { if (issue.editable()) setBorrowerId(id); }}
            membershipOn={membershipOn}
          />
          <DirectLoanItems
            key={formKey}
            disabled={issue.isPending}
            canEdit={issue.editable}
            products={activeProducts}
            productsLoading={products.isLoading}
            containers={containersOn ? containerOptions : null}
            containersLoading={containers.isLoading}
            containerId={containerId}
            onContainerChange={(id) => { if (issue.editable()) setContainerId(id); }}
            lines={lineRows}
            setLines={(value) => { if (issue.editable()) setLineRows(value); }}
            scanned={scanned}
            setScanned={(value) => { if (issue.editable()) setScanned(value); }}
            qrPayloads={qrPayloads}
            onQrPayloadsChange={(value) => { if (issue.editable()) setQrPayloads(value); }}
          />
          <div className="grid gap-4 md:grid-cols-2">
            <EvidenceUpload key={formKey} makerspaceId={makerspace.id} evidenceType="issue" label="Issue photo" disabled={issue.isPending} onUploaded={(id) => { if (issue.editable()) setIssueEvidenceId(id); }} />
            <Field label="Issue remark">
              <Textarea rows={3} value={issueRemark} disabled={issue.isPending} onChange={(event) => { if (issue.editable()) setIssueRemark(event.target.value); }} />
            </Field>
          </div>
          <ErrorText message={issue.error?.message} />
          <ErrorText message={products.error?.message} />
          <ErrorText message={containers.error?.message} />
          <div className="flex flex-col gap-3 border-t border-line pt-5 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-body-ui text-ink-muted" aria-live="polite">
              {missing.length ? `Before issuing: ${missing.join(", ")}.` : "Ready to issue."}
            </p>
            <Button variant="primary" disabled={!canIssue} loading={issue.isPending} loadingLabel="Issuing…" onClick={submitIssue}>
              Issue direct handout
            </Button>
          </div>
        </Card>
        {claimCodesOn ? <MemberClaimCodes makerspaceId={makerspace.id} members={memberOptions} membershipOn={membershipOn} /> : null}
        <div className="grid gap-3">
          <DirectLoanList loans={loans.results} loading={loans.isLoading} error={loans.error} onReturn={openReturnModal} />
          <Pagination page={loans.page} totalPages={loans.totalPages} onChange={loans.setPage} count={loans.count} pageSize={loans.pageSize} />
        </div>
      </div>
      <DirectLoanReturnModal
        key={returnVisit}
        canEdit={returnLoan.editable}
        loan={returningLoan}
        makerspaceId={makerspace.id}
        evidenceId={returnEvidenceId}
        notes={returnNotes}
        qrPayload={returnQrPayload}
        pending={returnLoan.isPending}
        error={returnLoan.error?.message ?? ""}
        onEvidenceUploaded={(id) => { if (returnLoan.editable()) setReturnEvidenceId(id); }}
        onNotesChange={(value) => { if (returnLoan.editable()) setReturnNotes(value); }}
        onQrPayloadChange={(value) => { if (returnLoan.editable()) setReturnQrPayload(value); }}
        onCancel={closeReturnModal}
        onSubmit={submitReturn}
      />
    </Panel>
  );
}
