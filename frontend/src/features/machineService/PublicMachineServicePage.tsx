import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { MakerspaceSiteHeader } from "../../components/chrome/PublicHeaders";
import { PublicContainer, PublicShell } from "../../components/chrome/PublicShell";
import { Button, Card, Dropdown, EmptyState, Field, PageHeader, Skeleton } from "../../components/ui";
import { useModules } from "../../lib/modules";
import { CheckinIdentityStep } from "../inventory/CheckinIdentityStep";
import type { CheckinMatch } from "../inventory/api";
import { PublicSignInCallout, memberSignInHref } from "../inventory/PublicSignInCallout";
import { useMakerspacePublic } from "../inventory/useMakerspacePublic";
import { usePublicSession } from "../inventory/usePublicSession";
import { serviceRequestPath } from "./publicApi";
import { ServiceRequestForm } from "./ServiceRequestForm";
import { ServiceStatusPanel, useServiceStatus } from "./ServiceStatusPanel";
import { useServiceTypes } from "./useServiceTypes";

export function PublicMachineServicePage({ defaultPrinter = false }: { defaultPrinter?: boolean }) {
  const space = useMakerspacePublic();
  const { makerspaceSlug: slug, bootstrap } = space;
  const modules = useModules();
  const enabled = modules.moduleEnabled("machines") && modules.moduleEnabled("machine_service")
    && (!defaultPrinter || modules.moduleEnabled("printing"));
  const catalog = useServiceTypes(slug, enabled);
  // Also filter cached catalog data when printing is switched off.
  const types = (catalog.data ?? []).filter((type) => !type.is_printer || modules.moduleEnabled("printing"));
  const [search] = useSearchParams();
  const [choice, setChoice] = useState<{ slug: string; id: string } | null>(null);
  const selection = choice?.slug === slug ? choice.id : null;
  const requestedType = selection ?? search.get("type") ?? "";
  const fallback = defaultPrinter ? types.find((type) => type.is_printer) : types.length === 1 ? types[0] : undefined;
  const selected = requestedType ? types.find((type) => String(type.id) === requestedType) : selection === null ? fallback : undefined;
  const [pending, setPending] = useState(false);
  const [checkin, setCheckin] = useState<{ slug: string; match: CheckinMatch | null } | null>(null);
  const confirmed = checkin?.slug === slug ? checkin.match : null;
  const checkedIn = bootstrap?.makerspace.request_access === "checked_in";
  const session = usePublicSession(slug, enabled && !checkedIn);
  const tracker = useServiceStatus(slug, enabled, defaultPrinter);
  const loading = modules.loading || space.bootstrapQuery.isLoading || (enabled && catalog.isLoading);
  const error = space.bootstrapQuery.error || catalog.error;
  const identityReady = checkedIn ? confirmed !== null : session.authenticated;

  return <PublicShell header={<MakerspaceSiteHeader {...space.header} moduleEnabled={modules.moduleEnabled} page="Service request" />}>
    <PublicContainer>
      <PageHeader kicker={space.displayName} title="Service request" description="Choose a machine type and describe your project. Staff will assign a machine." />
      <div className="mt-8 grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
        <section aria-label="Service request" className="min-w-0 space-y-5">
          {loading ? <Card aria-busy="true" aria-label="Loading service types"><Skeleton className="h-11 w-full" /></Card> : null}
          {!loading && error ? <EmptyState tone="error" title="Service requests didn't load" description={error.message}
            action={<Button onClick={() => { space.bootstrapQuery.refetch(); catalog.refetch(); }}>Try again</Button>} /> : null}
          {!loading && !error && (!enabled || !types.length) ? <EmptyState title="No service types available"
            description="This makerspace has no published machines accepting service requests right now. Check back later." /> : null}
          {!loading && !error && enabled && types.length > 0 ? <>
            <Card>
              <Field label="Machine type" helperText="Request a type of machine; staff will choose the equipment.">
                <Dropdown value={selected ? String(selected.id) : ""} disabled={pending} onChange={(event) => setChoice({ slug, id: event.target.value })}>
                  <option value="">Choose a machine type</option>
                  {types.map((type) => <option key={type.id} value={type.id}>{type.name}</option>)}
                </Dropdown>
              </Field>
              {requestedType && !selected ? <p className="mt-3 text-body-ui text-ink-muted">That machine type is unavailable. Choose another type.</p> : null}
            </Card>
            {selected ? (!checkedIn && !session.settled && !session.authenticated ?
              <Card aria-busy="true" aria-label="Checking sign-in"><Skeleton className="h-11 w-full" /></Card> :
              !checkedIn && session.signedOut ? <PublicSignInCallout href={memberSignInHref(space.header.homePath, modules.moduleEnabled("member_accounts"))}>
                Service requests are filed under your account.
              </PublicSignInCallout> : <ServiceRequestForm
                key={`${slug}:${selected.id}`} slug={slug} type={selected} identityReady={identityReady}
                identity={checkedIn && confirmed ? { name: confirmed.name, checkin_mid: confirmed.mid } : {}}
                identityStep={checkedIn ? <CheckinIdentityStep makerspaceSlug={slug} confirmed={confirmed} onConfirm={(match) => setCheckin({ slug, match })} disabled={pending} /> : undefined}
                onPendingChange={setPending} onSuccess={tracker.onSuccess}
              />) : null}
          </> : null}
        </section>
        {enabled ? <aside aria-label="Service request status"><ServiceStatusPanel tracker={tracker} statusPath={serviceRequestPath(space.tenantPath)} /></aside> : null}
      </div>
    </PublicContainer>
  </PublicShell>;
}
