import { Link } from "react-router-dom";

import { MakerspaceSiteHeader } from "../../components/chrome/PublicHeaders";
import { PublicContainer, PublicShell } from "../../components/chrome/PublicShell";
import { MakerspaceBrand } from "../../components/MakerspaceBrand";
import { Card, EmptyState, PageHeader, Skeleton, buttonClasses } from "../../components/ui";
import { featureEnabled } from "../../lib/features";
import { useModules } from "../../lib/modules";
import { getSessionGeneration } from "../../lib/apiSession";
import { PublicSelfCheckoutView } from "./PublicSelfCheckoutView";
import { PublicSignInCallout, memberSignInHref } from "./PublicSignInCallout";
import { useMakerspacePublic } from "./useMakerspacePublic";
import { usePublicSession } from "./usePublicSession";

export function PublicSelfCheckoutPage() {
  const space = useMakerspacePublic();
  const { tenant, makerspaceSlug, tenantPath, bootstrapQuery, bootstrap, displayName } = space;
  const { moduleEnabled } = useModules();
  const features = tenant.mode === "single" ? tenant.bootstrap?.features ?? [] : bootstrap?.features ?? [];
  const requiresCheckin = bootstrap?.makerspace.request_access === "checked_in";
  // Off the check-in roster the backend demands membership, waiver and presence, which
  // nobody can hold with `membership` off, so the feature alone does not make it usable.
  const enabled =
    featureEnabled(features, "inventory.self_checkout") &&
    (requiresCheckin || moduleEnabled("membership"));
  // Off the roster the loan is the signed-in member's own.
  const session = usePublicSession(makerspaceSlug, enabled && !requiresCheckin);
  const needsSignIn = !requiresCheckin && session.signedOut;
  const ready = !bootstrapQuery.isLoading && !bootstrapQuery.isError;

  return (
    <PublicShell header={<MakerspaceSiteHeader {...space.header} moduleEnabled={moduleEnabled} page="Tool checkout" />}>
      <PublicContainer width="sm">
        <PageHeader
          kicker="Public tool checkout"
          title={<MakerspaceBrand name={displayName} logoUrl={bootstrap?.makerspace?.logo_url} size="lg" />}
          description="Scan a physical tool label to check it out or return it."
        />

        <div className="mt-8">
          {bootstrapQuery.isLoading ? (
            <Card aria-busy="true" aria-label="Loading checkout access" className="space-y-3">
              <Skeleton className="h-10 w-full rounded-full" />
              <Skeleton className="h-24 w-full" />
              <Skeleton className="h-11 w-full rounded-full" />
            </Card>
          ) : null}

          {bootstrapQuery.isError ? (
            <EmptyState tone="error" title="Checkout access didn't load" description="Try again in a moment." />
          ) : null}

          {ready && !enabled ? (
            <EmptyState
              title="Self-checkout is not enabled for this makerspace."
              description="Browse the inventory and send a borrow request instead."
              action={<Link className={buttonClasses({ variant: "secondary" })} to={tenantPath()}>Back to inventory</Link>}
            />
          ) : null}

          {ready && enabled && needsSignIn ? (
            <PublicSignInCallout href={memberSignInHref(space.header.homePath, moduleEnabled("member_accounts"))}>
              Self-checkout is recorded under your member account.
            </PublicSignInCallout>
          ) : null}

          {ready && enabled && !needsSignIn ? (
            <PublicSelfCheckoutView
              key={JSON.stringify([makerspaceSlug, getSessionGeneration(), requiresCheckin])}
              makerspaceSlug={makerspaceSlug} requiresCheckin={requiresCheckin}
              sessionReady={session.settled && session.authenticated} />
          ) : null}
        </div>
      </PublicContainer>
    </PublicShell>
  );
}
