import { lazy, Suspense } from "react";

import { SectionHeading, Skeleton } from "../../components/ui";
import type { StaffAuthUser } from "../../lib/api";
import { canManagePlatform } from "./staffSelection";
import { StaffPanelErrorBoundary } from "./StaffPanelErrorBoundary";

const PlatformEmailPanel = lazy(() => import("./PlatformEmailPanel").then((m) => ({ default: m.PlatformEmailPanel })));
const PlatformSocialAuthPanel = lazy(() => import("./PlatformSocialAuthPanel").then((m) => ({ default: m.PlatformSocialAuthPanel })));
const PlatformStripeConnectPanel = lazy(() => import("./PlatformStripeConnectPanel").then((m) => ({ default: m.PlatformStripeConnectPanel })));

export function PlatformSettingsPanels({ user, singleTenantLocked = false }: { user: StaffAuthUser; singleTenantLocked?: boolean }) {
  if (!canManagePlatform(user, singleTenantLocked)) return null;
  const stripeAvailable = user.staff_context?.platform_hosting === true &&
    user.staff_context.platform_stripe_connect_available === true;
  return (
    <StaffPanelErrorBoundary resetKey="platform">
      <Suspense fallback={<Skeleton className="h-40 w-full" />}>
        <section className="grid min-w-0 gap-6">
          <SectionHeading title="Shared settings" description={`Email delivery, sign-in providers${stripeAvailable ? " and payouts" : ""} for every makerspace on this deployment.`} />
          <div className="grid min-w-0 gap-6">
            <PlatformEmailPanel />
            <PlatformSocialAuthPanel />
            {stripeAvailable ? <PlatformStripeConnectPanel /> : null}
          </div>
        </section>
      </Suspense>
    </StaffPanelErrorBoundary>
  );
}
