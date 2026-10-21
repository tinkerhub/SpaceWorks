import { MakerspaceSiteHeader } from "../../components/chrome/PublicHeaders";
import { PublicContainer, PublicShell } from "../../components/chrome/PublicShell";
import { MakerspaceBrand } from "../../components/MakerspaceBrand";
import { EmptyState, PageHeader, Skeleton } from "../../components/ui";
import { useModules } from "../../lib/modules";
import { useMakerspacePublic } from "../inventory/useMakerspacePublic";
import { usePublicStats, type PublicStatsResponse } from "./api";
import { CurrentLoansSection, HardwareSection, PrintingSection } from "./StatsSections";

export function PublicStatsPage() {
  const space = useMakerspacePublic();
  const { makerspaceSlug, bootstrap, displayName } = space;
  const statsQuery = usePublicStats(makerspaceSlug);
  const { moduleEnabled } = useModules();

  return (
    <PublicShell header={<MakerspaceSiteHeader {...space.header} moduleEnabled={moduleEnabled} page="Stats" />}>
      <PublicContainer>
        <PageHeader
          kicker="Public stats"
          title={<MakerspaceBrand name={displayName} logoUrl={bootstrap?.makerspace?.logo_url} size="lg" />}
          description="Live community activity from the public catalog."
        />

        <div className="mt-8 space-y-10">
          {statsQuery.isLoading ? <LoadingState /> : null}

          {statsQuery.isError ? (
            <EmptyState
              tone="error"
              title="Stats not available"
              description="This makerspace has its public stats page turned off, or it may not exist."
            />
          ) : null}

          {statsQuery.data && isEmptyStats(statsQuery.data) ? (
            <EmptyState
              title="No public activity yet"
              description="Stats will appear after this makerspace publishes tools or records public loans and print activity."
            />
          ) : null}

          {statsQuery.data && !isEmptyStats(statsQuery.data) ? (
            <>
              {statsQuery.data.printing ? <PrintingSection printing={statsQuery.data.printing} /> : null}
              <HardwareSection hardware={statsQuery.data.hardware} />
              <CurrentLoansSection loans={statsQuery.data.current_loans} />
            </>
          ) : null}
        </div>
      </PublicContainer>
    </PublicShell>
  );
}

function LoadingState() {
  return (
    <div className="space-y-4" aria-busy="true" aria-label="Loading stats">
      <Skeleton className="h-6 w-40" />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[0, 1, 2, 3].map((item) => <Skeleton key={item} className="h-24 w-full rounded-lg" />)}
      </div>
      <Skeleton className="h-48 w-full rounded-lg" />
    </div>
  );
}

function isEmptyStats(stats: PublicStatsResponse) {
  return (
    stats.printing === null &&
    stats.hardware.library.library_size === 0 &&
    stats.hardware.most_popular.length === 0 &&
    stats.hardware.tools_out.length === 0 &&
    stats.hardware.recently_added.length === 0 &&
    stats.current_loans.length === 0
  );
}
