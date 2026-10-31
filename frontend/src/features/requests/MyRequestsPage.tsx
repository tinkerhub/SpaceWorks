import { NotFoundPage } from "../../components/NotFoundPage";
import { MakerspaceSiteHeader } from "../../components/chrome/PublicHeaders";
import { PublicContainer, PublicShell } from "../../components/chrome/PublicShell";
import { Button, EmptyState, Loader, PageHeader } from "../../components/ui";
import { useModules } from "../../lib/modules";
import { useMakerspacePublic } from "../inventory/useMakerspacePublic";
import { usePublicSession } from "../inventory/usePublicSession";
import { MyRequestsPanel } from "./MyRequestsPanel";

export function MyRequestsPage() {
  const space = useMakerspacePublic();
  const modules = useModules();
  const hardwareOn = modules.moduleEnabled("request_workflow");
  const machineOn = modules.moduleEnabled("machine_service");
  const memberAccountsOn = modules.moduleEnabled("member_accounts");
  usePublicSession(space.makerspaceSlug, Boolean(space.bootstrap) && memberAccountsOn && (hardwareOn || machineOn));
  if (modules.loading || space.tenant.loading || space.bootstrapQuery.isLoading) return <Loader label="Loading requests" />;
  if (space.bootstrapQuery.error || space.tenant.error) return <EmptyState tone="error" title="Requests didn't load"
    description="The makerspace could not be loaded. Please try again."
    action={<Button onClick={() => void space.bootstrapQuery.refetch()}>Try again</Button>} />;
  if (!space.bootstrap || (!hardwareOn && !machineOn)) return <NotFoundPage />;
  return <PublicShell header={<MakerspaceSiteHeader {...space.header} moduleEnabled={modules.moduleEnabled} page="My requests" />}>
    <PublicContainer width="md">
      <PageHeader kicker={space.displayName} title="My requests" description="Track hardware loans and machine service requests in this makerspace." />
      <div className="mt-8"><MyRequestsPanel slug={space.makerspaceSlug} hardwareOn={hardwareOn} machineOn={machineOn}
        memberAccountsOn={memberAccountsOn} basePath={space.header.homePath.replace(/\/+$/, "")}
        memberAreaHref={memberAccountsOn ? space.tenantPath("member") : undefined} /></div>
    </PublicContainer>
  </PublicShell>;
}
