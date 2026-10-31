import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { MakerspaceSiteHeader } from "../../components/chrome/PublicHeaders";
import { PublicContainer, PublicShell } from "../../components/chrome/PublicShell";
import { Button, Card, Dropdown, EmptyState, Field, PageHeader, Skeleton } from "../../components/ui";
import { useModules } from "../../lib/modules";
import { useAuthActionOwner, type AuthAction } from "../auth/useAuthActionOwner";
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
  const modules = useModules();
  const enabled = modules.moduleEnabled("machines") && modules.moduleEnabled("machine_service")
    && (!defaultPrinter || modules.moduleEnabled("printing"));
  const session = usePublicSession(space.makerspaceSlug, enabled && space.bootstrap?.makerspace.request_access !== "checked_in");
  const scope = JSON.stringify([space.makerspaceSlug, space.bootstrap?.makerspace.request_access,
    defaultPrinter, enabled, modules.moduleEnabled("printing")]);
  const owner = useAuthActionOwner(scope);
  return <ServiceVisit key={JSON.stringify([scope, owner.context.epoch])} space={space} modules={modules}
    session={session} enabled={enabled} defaultPrinter={defaultPrinter} isPageCurrent={owner.isContextCurrent} />;
}

function ServiceVisit({ space, modules, session, enabled, defaultPrinter, isPageCurrent }: {
  space: ReturnType<typeof useMakerspacePublic>;
  modules: ReturnType<typeof useModules>;
  session: ReturnType<typeof usePublicSession>;
  enabled: boolean;
  defaultPrinter: boolean;
  isPageCurrent: () => boolean;
}) {
  const { makerspaceSlug: slug, bootstrap } = space;
  const catalog = useServiceTypes(slug, enabled);
  // Also filter cached catalog data when printing is switched off.
  const types = (catalog.data ?? []).filter((type) => !type.is_printer || modules.moduleEnabled("printing"));
  const [search] = useSearchParams();
  const [choice, setChoice] = useState<{ slug: string; id: string } | null>(null);
  const selection = choice?.slug === slug ? choice.id : null;
  const requestedType = selection ?? search.get("type") ?? "";
  const fallback = defaultPrinter ? types.find((type) => type.is_printer) : types.length === 1 ? types[0] : undefined;
  const selected = requestedType ? types.find((type) => String(type.id) === requestedType) : selection === null ? fallback : undefined;
  const [confirmed, setConfirmed] = useState<CheckinMatch | null>(null);
  const checkedIn = bootstrap?.makerspace.request_access === "checked_in";
  const person = JSON.stringify([confirmed?.mid, confirmed?.name]);
  const tracker = useServiceStatus(slug, enabled, defaultPrinter, person);
  const loading = modules.loading || space.bootstrapQuery.isLoading || (enabled && catalog.isLoading);
  const error = space.bootstrapQuery.error || catalog.error;
  const identityReady = checkedIn ? confirmed !== null : session.authenticated;
  const formVisible = !loading && !error && enabled && Boolean(selected)
    && (checkedIn || session.authenticated);
  const admissionOwner = useAuthActionOwner(JSON.stringify([selected?.id, person, formVisible]));
  const [admission, setAdmission] = useState<{ context: typeof admissionOwner.context; action: AuthAction } | null>(null);
  const pending = formVisible && admission?.context === admissionOwner.context;
  function isFormCurrent() { return isPageCurrent() && admissionOwner.isIntentCurrent(); }
  function onPendingChange(next: boolean, action: AuthAction) {
    if (!isPageCurrent()) return;
    if (next) {
      if (isFormCurrent()) setAdmission({ context: admissionOwner.context, action });
    } else {
      // Disappearance releases only this action; obsolete cleanup cannot unlock B.
      setAdmission((current) => current?.action === action ? null : current);
    }
  }
  function changePerson(match: CheckinMatch | null) {
    if (!isFormCurrent()) return;
    if (confirmed?.mid !== match?.mid || confirmed?.name !== match?.name) admissionOwner.cancel();
    setConfirmed(match);
  }

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
                <Dropdown value={selected ? String(selected.id) : ""} disabled={pending} onChange={(event) => {
                  if (!isFormCurrent()) return;
                  if (selected && event.target.value === String(selected.id)) return;
                  admissionOwner.cancel();
                  setChoice({ slug, id: event.target.value });
                }}>
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
              </PublicSignInCallout> : <>
              {checkedIn ? <Card><CheckinIdentityStep makerspaceSlug={slug} confirmed={confirmed}
                onConfirm={changePerson} disabled={pending} /></Card> : null}
              <ServiceRequestForm
                key={JSON.stringify([selected.id, person])} slug={slug} type={selected} identityReady={identityReady}
                identity={checkedIn && confirmed ? { name: confirmed.name, checkin_mid: confirmed.mid } : {}}
                isVisitCurrent={isFormCurrent} onPendingChange={onPendingChange} onSuccess={tracker.onSuccess}
              /></>) : null}
          </> : null}
        </section>
        {enabled ? <aside aria-label="Service request status"><ServiceStatusPanel tracker={tracker} statusPath={serviceRequestPath(space.tenantPath)} savedRequestsPath={space.tenantPath("my-requests")} /></aside> : null}
      </div>
    </PublicContainer>
  </PublicShell>;
}
