import { Link, Navigate, useLocation } from "react-router-dom";

import { StaffTabContent } from "./StaffTabContent";
import { StaffShell } from "./shell/StaffShell";
import { Button, Chip, EmptyState } from "../../components/ui";
import { documentTitle, useDocumentTitle } from "../../lib/useDocumentTitle";
import { getStaffAccess, STAFF_TAB_KEYS, TAB_LABELS } from "./staffAccess";
import {
  filterTabsByEnabledModules,
  readStoredStaffTab,
  keptStaffSubPath,
  staffSubPathFromPath,
  staffTabPath,
  tabFromStaffPath,
} from "./staffTabs";
import type { StaffAuthUser } from "../../lib/api";
import type { Makerspace } from "./panels/shared";
import { canManagePlatform, isGlobalStaffAdmin } from "./staffSelection";

export function StaffWorkspace({
  activeMakerspace,
  actions,
  isMachineOnly,
  canConfigureMachineTypes,
  guestOnly,
  isSuperadmin,
  makerspaces,
  onAuthRefresh,
  selected,
  setSelected,
  setTab,
  signOut,
  singleTenantLocked,
  user,
}: {
  activeMakerspace?: Makerspace;
  actions: readonly string[];
  isMachineOnly: boolean;
  canConfigureMachineTypes: boolean;
  guestOnly: boolean;
  isSuperadmin: boolean;
  makerspaces: Makerspace[];
  onAuthRefresh: () => void;
  selected: number | null;
  setSelected: (id: number | null) => void;
  setTab: (tab: string) => void;
  signOut: () => Promise<void>;
  singleTenantLocked: boolean;
  user: StaffAuthUser;
}) {
  const location = useLocation();
  const canPickMakerspace = isGlobalStaffAdmin(user) && !singleTenantLocked;
  const {
    allowedTabs,
    canChooseToBuyKind,
    canEditInventory,
    canIssueDirectLoan,
    canIssueRequest,
    canReturnRequest,
    canReviewRequests,
    canCancelRequests,
    canCollectServiceRequests,
    canManageMakerspace,
    canManageEvents,
    canManageBookings,
    canManageMachines,
    canManageQr,
    canSeeHardware,
    canSeePrinting,
    canUseToBuy,
    canViewAudit,
    defaultTab,
    handoutOnly,
    printingOnly,
  } = getStaffAccess(actions, isSuperadmin, singleTenantLocked, isMachineOnly);
  const visibleMakerspaces =
    singleTenantLocked && activeMakerspace
      ? [activeMakerspace]
      : makerspaces;
  const platformAvailable = !guestOnly && canManagePlatform(user, singleTenantLocked);
  const scopedTabs = filterTabsByEnabledModules(allowedTabs, activeMakerspace).filter((tab) => tab !== "platform");
  const moduleAllowedTabs = platformAvailable ? [...scopedTabs, "platform"] : scopedTabs;
  const routeTab = tabFromStaffPath(location.pathname, guestOnly);
  const routeTabDenied =
    !!routeTab && STAFF_TAB_KEYS.includes(routeTab) && !moduleAllowedTabs.includes(routeTab);
  const requestedTab = routeTab || readStoredStaffTab();
  const activeTab = moduleAllowedTabs.includes(requestedTab)
    ? requestedTab
    : moduleAllowedTabs.includes(defaultTab)
      ? defaultTab
      : moduleAllowedTabs[0] ?? "";
  // Without this the redirect below strips `/admin/machines/12-laser` back to
  // `/admin/machines` on every load, because the two strings differ -- so a per-type deep
  // link could never survive its first render. The rule lives in `keptStaffSubPath` so it
  // is testable on its own; rendering this whole workspace to assert one path string is
  // how that regression stays uncaught.
  const keptSubPath = keptStaffSubPath(
    routeTab,
    activeTab,
    staffSubPathFromPath(location.pathname, guestOnly),
  );
  const activeTabPath = activeTab
    ? staffTabPath(activeTab, guestOnly, guestOnly ? undefined : activeMakerspace?.slug, singleTenantLocked, keptSubPath)
    : staffTabPath(defaultTab, guestOnly, guestOnly ? undefined : activeMakerspace?.slug, singleTenantLocked);
  // Label the authority effective in this space; global chooser access is separate.
  const activeRoleName = isSuperadmin
    ? "Super Admin"
    : user.makerspaces.find((item) => item.id === selected)?.role_name;

  // Tabs OMITTED by design rather than genuinely forbidden: `requests` holds hardware rows
  // a machine-only actor never has, and `notifications` is withheld from that same actor
  // because the inbox cannot be machine-scoped. Both are absent from the sidebar, so a
  // stored or deep-linked route to one is a stale bookmark, not an attempt to reach
  // something restricted — it should land on the actor's first allowed tab rather than an
  // access-denied page. Genuinely denied tabs still render the denial.
  const normalizedDeniedTabs = new Set(["requests", "notifications"]);
  const normalizeDenied = routeTabDenied && !!routeTab && normalizedDeniedTabs.has(routeTab);
  const workspaceName = activeMakerspace?.name ?? "Inventory Control";
  useDocumentTitle(documentTitle(routeTabDenied ? "Access denied" : TAB_LABELS[activeTab], activeMakerspace?.name));
  if (activeTab && (!routeTabDenied || normalizeDenied) && location.pathname !== activeTabPath) {
    return <Navigate replace to={activeTabPath} />;
  }

  const publicInventoryPath = activeMakerspace
    ? singleTenantLocked ? "/" : "/m/" + activeMakerspace.slug
    : null;

  return (
    <StaffShell
      nav={{
        activeMakerspaceSlug: guestOnly ? undefined : activeMakerspace?.slug,
        activeTab: routeTabDenied ? "" : activeTab,
        allowedTabs: moduleAllowedTabs,
        guestOnly,
        singleTenantLocked,
      }}
      account={{
        username: user.username,
        roleName: activeRoleName,
        activeMakerspaceName: activeMakerspace?.name,
        makerspaces,
        selected,
        canSwitchMakerspace: !singleTenantLocked && makerspaces.length > 1,
        canPickMakerspace,
        onPickMakerspace: () => setSelected(null),
        onSelectMakerspace: setSelected,
        onSignOut: signOut,
      }}
      activeMakerspaceId={activeMakerspace?.id}
      publicPath={publicInventoryPath}
      workspaceName={workspaceName}
      user={user}
      onPasswordChanged={onAuthRefresh}
      onSelectTab={setTab}
    >
      {/* Context strip, not a heading: each panel's PageHeader is the page's one h1. */}
      <div className="mb-6 flex min-w-0 flex-wrap items-center gap-2 border-b border-line pb-4">
        <p className="min-w-0 break-words text-body-ui font-semibold text-ink">{workspaceName}</p>
        {activeRoleName ? <Chip size="sm">{activeRoleName}</Chip> : null}
        {activeMakerspace ? (
          <Chip size="sm" tone="outline" className="font-mono">{activeMakerspace.public_code ?? activeMakerspace.slug}</Chip>
        ) : null}
        {canPickMakerspace ? (
          <Button variant="secondary" size="sm" className="ml-auto hidden md:inline-flex" onClick={() => setSelected(null)}>
            Switch makerspace
          </Button>
        ) : null}
      </div>
      {!activeTab ? (
        <EmptyState title="No operational access" description="This account has no available staff pages for this makerspace. Choose another makerspace or sign out from your account menu." />
      ) : routeTabDenied ? (
        <EmptyState
          title="Access denied"
          description="You don't have permission to view this page, or it isn't enabled for this makerspace."
          action={
            <Button asChild variant="primary">
              <Link to={activeTabPath}>Go to {TAB_LABELS[activeTab] ?? "your workspace"}</Link>
            </Button>
          }
        />
      ) : (
        <StaffTabContent
          activeMakerspace={activeMakerspace}
          activeTab={activeTab}
          guestOnly={guestOnly || handoutOnly}
          makerspaces={visibleMakerspaces}
          isSuperadmin={isSuperadmin}
          currentUser={user}
          onAuthRefresh={onAuthRefresh}
          printingOnly={printingOnly}
          canChooseToBuyKind={canChooseToBuyKind}
          canEditInventory={canEditInventory}
          canIssueDirectLoan={canIssueDirectLoan}
          canIssueRequest={canIssueRequest}
          canReturnRequest={canReturnRequest}
          canReviewRequests={canReviewRequests}
          canCancelRequests={canCancelRequests}
          canCollectServiceRequests={canCollectServiceRequests}
          canUseToBuy={canUseToBuy}
          canManageQr={canManageQr}
          canManageMakerspace={canManageMakerspace}
          canManageEvents={canManageEvents}
          canManageBookings={canManageBookings}
          canManageMachines={canManageMachines}
          isMachineOnly={isMachineOnly}
          canConfigureMachineTypes={canConfigureMachineTypes}
          canSeeHardware={canSeeHardware}
          canSeePrinting={canSeePrinting}
          canViewAudit={canViewAudit}
          singleTenantLocked={singleTenantLocked}
        />
      )}
    </StaffShell>
  );
}
