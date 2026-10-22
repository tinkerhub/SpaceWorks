import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import type { ArchivedPaymentSummary } from "../../generated/api";
import { StructuredApiError, staffRequest } from "../../lib/api";
import { PlatformSiteHeader } from "../../components/chrome/PublicHeaders";
import { PublicContainer, PublicShell } from "../../components/chrome/PublicShell";
import { Chip, EmptyState, ErrorText, Loader, PageHeader, Spinner, buttonClasses, useToast } from "../../components/ui";
import { AccountCard } from "../account/AccountCard";
import { MemberAuthPanel } from "./MemberAuthPanel";
import { MemberPaymentRows, type MemberPayment } from "./MemberPayments";

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Unable to load archived payments.";
}

function ArchivedMakerspacePayments({ summary }: { summary: ArchivedPaymentSummary }) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const payments = useQuery({
    queryKey: ["member", "archived-payments", summary.makerspace.id, "payments"],
    queryFn: () => staffRequest<MemberPayment[]>(
      `/member/makerspaces/${summary.makerspace.id}/payments`,
    ),
    retry: false,
  });
  const checkout = useMutation({
    mutationFn: (paymentId: number) => staffRequest<{ checkout_url: string }>(
      `/member/makerspaces/${summary.makerspace.id}/payments/${paymentId}/checkout`,
      { method: "POST" },
    ),
    onSuccess: ({ checkout_url }) => {
      void queryClient.invalidateQueries({
        queryKey: ["member", "archived-payments", summary.makerspace.id, "payments"],
      });
      window.location.assign(checkout_url);
    },
    onError: () => showToast("Could not create a payment link", { tone: "error" }),
  });

  return (
    <AccountCard
      title={summary.makerspace.name}
      description="This makerspace is closed. Outstanding charges can still be settled and receipts remain readable here."
      action={<Chip tone={summary.pending_count ? "warning" : "neutral"}><span className="font-mono">{summary.pending_count}</span> pending · <span className="font-mono">{summary.total_count}</span> total</Chip>}
    >
      <div className="flex flex-col gap-3">
        {payments.isLoading ? (
          <p className="inline-flex items-center gap-2 text-body-ui text-ink-muted"><Spinner decorative className="size-4" />Loading payment history…</p>
        ) : null}
        <ErrorText message={payments.isError ? errorMessage(payments.error) : null} />
        {payments.data ? (
          <MemberPaymentRows
            payments={payments.data}
            checkoutPaymentId={checkout.isPending ? checkout.variables : undefined}
            onCheckout={(paymentId) => checkout.mutate(paymentId)}
          />
        ) : null}
        <ErrorText message={checkout.isError ? errorMessage(checkout.error) : null} />
      </div>
    </AccountCard>
  );
}

export function ArchivedPayments() {
  const queryClient = useQueryClient();
  const discovery = useQuery({
    queryKey: ["member", "archived-payments"],
    queryFn: () => staffRequest<ArchivedPaymentSummary[]>("/member/archived-payments"),
    retry: false,
  });
  const unauthenticated = discovery.error instanceof StructuredApiError
    && discovery.error.status === 401;
  // `payments` is a separable app. On a deployment that tombstones it the endpoint is
  // spliced out entirely, so this route must read as absent rather than as a permanent
  // error -- and it cannot ask tenant bootstrap which modules exist, because not depending
  // on bootstrap is the whole reason this route exists. The 404 IS the availability signal.
  const removed = discovery.error instanceof StructuredApiError
    && discovery.error.status === 404;

  const backHome = <Link className={buttonClasses({ variant: "secondary" })} to="/">Back to Space Works</Link>;

  if (removed) {
    return (
      <PublicShell header={<PlatformSiteHeader page="Page not found" />}>
        <PublicContainer width="sm" className="flex flex-1 flex-col justify-center">
          <div className="flex flex-col items-center gap-3 text-center">
            <h1 className="text-h1 text-ink">Page not found</h1>
            <p className="text-body-ui text-ink-secondary">There is nothing at this address on this deployment.</p>
            <div className="mt-2">{backHome}</div>
          </div>
        </PublicContainer>
      </PublicShell>
    );
  }

  if (unauthenticated) {
    return (
      <MemberAuthPanel
        onAuthenticated={() => {
          void queryClient.invalidateQueries({
            queryKey: ["member", "archived-payments"],
          });
        }}
      />
    );
  }

  return (
    <PublicShell header={<PlatformSiteHeader page="Archived payments" />}>
      <PublicContainer width="md" className="flex flex-col gap-6">
        <PageHeader
          kicker="Archived makerspaces"
          title="Payments and receipts"
          description="Closed makerspaces no longer appear in the normal member area. This page remains available so outstanding charges can be settled and past receipts can be read."
        />
        {discovery.isLoading ? (
          <div className="flex justify-center py-10"><Loader label="Loading archived makerspace charges" /></div>
        ) : null}
        {discovery.isError ? <ErrorText message={errorMessage(discovery.error)} /> : null}
        {discovery.data?.length === 0 ? (
          <EmptyState title="No archived payments" description="No charges outstanding from closed makerspaces." action={backHome} />
        ) : null}
        {discovery.data?.map((summary) => (
          <ArchivedMakerspacePayments key={summary.makerspace.id} summary={summary} />
        ))}
        {discovery.data?.length === 0 ? null : <div>{backHome}</div>}
      </PublicContainer>
    </PublicShell>
  );
}
