import { lazy, Suspense } from "react";

import { Skeleton } from "../../components/ui";
import type { StaffAuthUser } from "../../lib/api";
import { featureEnabled } from "../../lib/features";
import { moduleEnabled } from "../../lib/modules";
import { Panel, type Makerspace } from "./panels/shared";
import { StaffPanelErrorBoundary } from "./StaffPanelErrorBoundary";

const DashboardPanel = lazy(() => import("./panels/DashboardPanel").then((m) => ({ default: m.DashboardPanel })));
const NotificationInbox = lazy(() => import("./panels/NotificationInbox").then((m) => ({ default: m.NotificationInbox })));
const DirectLoans = lazy(() => import("./DirectLoans").then((m) => ({ default: m.DirectLoans })));
const Inventory = lazy(() => import("./panels/Inventory").then((m) => ({ default: m.Inventory })));
const Ledger = lazy(() => import("./panels/Ledger").then((m) => ({ default: m.Ledger })));
const MachinesPanel = lazy(() => import("./panels/MachinesPanel").then((m) => ({ default: m.MachinesPanel })));
const EventsPanel = lazy(() => import("./EventsPanel").then((m) => ({ default: m.EventsPanel })));
const BookingsPanel = lazy(() => import("./BookingsPanel").then((m) => ({ default: m.BookingsPanel })));
const MembersPanel = lazy(() => import("./MembersPanel").then((m) => ({ default: m.MembersPanel })));
const QrTools = lazy(() => import("./panels/QrTools").then((m) => ({ default: m.QrTools })));
const RequestsPanel = lazy(() => import("./panels/RequestsPanel").then((m) => ({ default: m.RequestsPanel })));
const Users = lazy(() => import("./panels/Users").then((m) => ({ default: m.Users })));
const OperationsReports = lazy(() => import("./panels/OperationsReports").then((m) => ({ default: m.OperationsReports })));
const AuditLog = lazy(() => import("./panels/AuditLog").then((m) => ({ default: m.AuditLog })));
const BulkImport = lazy(() => import("./panels/BulkImport").then((m) => ({ default: m.BulkImport })));
const ScannerPanel = lazy(() => import("./panels/ScannerPanel").then((m) => ({ default: m.ScannerPanel })));
const EmailTemplatesPanel = lazy(() => import("./panels/EmailTemplatesPanel").then((m) => ({ default: m.EmailTemplatesPanel })));
const ContainersPanel = lazy(() => import("./panels/ContainersPanel").then((m) => ({ default: m.ContainersPanel })));
const StocktakePanel = lazy(() => import("./panels/StocktakePanel").then((m) => ({ default: m.StocktakePanel })));
const StockTransferPanel = lazy(() => import("./panels/StockTransferPanel").then((m) => ({ default: m.StockTransferPanel })));
const ProcurementPanel = lazy(() => import("./panels/ProcurementPanel").then((m) => ({ default: m.ProcurementPanel })));
const EmailLogPanel = lazy(() => import("./panels/EmailLogPanel").then((m) => ({ default: m.EmailLogPanel })));
const WarrantyPanel = lazy(() => import("./panels/WarrantyPanel").then((m) => ({ default: m.WarrantyPanel })));
const AccountabilityPanel = lazy(() => import("./panels/AccountabilityPanel").then((m) => ({ default: m.AccountabilityPanel })));
const Categories = lazy(() => import("./panels/Categories").then((m) => ({ default: m.Categories })));
const NeedsFixShelf = lazy(() => import("./panels/NeedsFixShelf").then((m) => ({ default: m.NeedsFixShelf })));
const ApiClientsPanel = lazy(() => import("./ApiClientsPanel").then((m) => ({ default: m.ApiClientsPanel })));
const PlatformEmailPanel = lazy(() => import("./PlatformEmailPanel").then((m) => ({ default: m.PlatformEmailPanel })));
const PlatformStripeConnectPanel = lazy(() => import("./PlatformStripeConnectPanel").then((m) => ({ default: m.PlatformStripeConnectPanel })));
const PlatformSocialAuthPanel = lazy(() => import("./PlatformSocialAuthPanel").then((m) => ({ default: m.PlatformSocialAuthPanel })));
const MakerspaceSettingsPanel = lazy(() => import("./MakerspaceSettingsPanel").then((m) => ({ default: m.MakerspaceSettingsPanel })));
const ModulesPanel = lazy(() => import("./ModulesPanel").then((m) => ({ default: m.ModulesPanel })));
const PaymentsPanel = lazy(() => import("./PaymentsPanel").then((m) => ({ default: m.PaymentsPanel })));
const HandoverConsole = lazy(() => import("./panels/machine/HandoverConsole").then((m) => ({ default: m.HandoverConsole })));
const DataExportsPanel = lazy(() => import("./DataExportsPanel").then((m) => ({ default: m.DataExportsPanel })));
const BackupRestorePanel = lazy(() => import("./BackupRestorePanel").then((m) => ({ default: m.BackupRestorePanel })));
const TenantMigrationPanel = lazy(() => import("./TenantMigrationPanel").then((m) => ({ default: m.TenantMigrationPanel })));

export function StaffTabContent({
  activeMakerspace,
  activeTab,
  guestOnly,
  makerspaces,
  isSuperadmin,
  currentUser,
  onAuthRefresh,
  printingOnly,
  canChooseToBuyKind,
  canEditInventory,
  canIssueDirectLoan,
  canReturnRequest,
  canReviewRequests,
  canCollectServiceRequests,
  canUseToBuy,
  canManageQr,
  canManageMakerspace,
  canManageMachines,
  isMachineOnly,
  canConfigureMachineTypes,
  canManageEvents,
  canManageBookings,
  canSeeHardware,
  canSeePrinting,
  canViewAudit,
  singleTenantLocked = false,
}: {
  activeMakerspace?: Makerspace;
  activeTab: string;
  guestOnly: boolean;
  makerspaces: Makerspace[];
  isSuperadmin: boolean;
  currentUser: StaffAuthUser;
  onAuthRefresh: () => void;
  printingOnly: boolean;
  canChooseToBuyKind: boolean;
  canEditInventory: boolean;
  canIssueDirectLoan: boolean;
  canReturnRequest: boolean;
  canReviewRequests: boolean;
  canCollectServiceRequests: boolean;
  canUseToBuy: boolean;
  canManageQr: boolean;
  canManageMakerspace: boolean;
  canManageMachines: boolean;
  isMachineOnly: boolean;
  canConfigureMachineTypes: boolean;
  canManageEvents: boolean;
  canManageBookings: boolean;
  canSeeHardware: boolean;
  canSeePrinting: boolean;
  canViewAudit: boolean;
  // Machine links, and hiding platform-only (deployment, aggregate) surfaces on an origin-locked site.
  singleTenantLocked?: boolean;
}) {
  if (!activeMakerspace) {
    return <Panel title="No makerspace">Assign a makerspace to this account.</Panel>;
  }
  const makerspaceKey = activeMakerspace.id;
  return (
    <StaffPanelErrorBoundary resetKey={`${makerspaceKey}:${activeTab}`}>
      <Suspense fallback={<div className="p-4"><Skeleton className="h-40 w-full" /></div>}>
      {activeTab === "dashboard" ? (
        <DashboardPanel key={makerspaceKey} makerspace={activeMakerspace} canManageMakerspace={canManageMakerspace} />
      ) : null}
      {activeTab === "notifications" ? (
        <NotificationInbox key={makerspaceKey} makerspace={activeMakerspace} />
      ) : null}
      {activeTab === "requests" ? (
        <RequestsPanel
          key={makerspaceKey}
          makerspace={activeMakerspace}
          guestOnly={guestOnly}
          canSeeHardware={canSeeHardware}
          canViewAudit={canViewAudit}
          canReturnRequest={canReturnRequest}
          canReviewRequests={canReviewRequests}
        />
      ) : null}
      {activeTab === "inventory" ? (
        <Inventory
          key={makerspaceKey}
          makerspace={activeMakerspace}
          canViewAudit={canViewAudit}
          canUseToBuy={canUseToBuy}
          canEditInventory={canEditInventory}
        />
      ) : null}
      {activeTab === "needsfix" && canEditInventory ? <NeedsFixShelf key={makerspaceKey} makerspace={activeMakerspace} /> : null}
      {activeTab === "categories" && canEditInventory ? <Categories key={makerspaceKey} makerspace={activeMakerspace} /> : null}
      {activeTab === "machines" ? (
        <MachinesPanel
          key={makerspaceKey}
          makerspaceId={activeMakerspace.id}
          canManage={canManageMachines}
          canConfigureMachineTypes={canConfigureMachineTypes}
          maintenanceEnabled={moduleEnabled(activeMakerspace.enabled_modules, "maintenance")}
          machineServiceEnabled={moduleEnabled(activeMakerspace.enabled_modules, "machine_service")}
          printingEnabled={moduleEnabled(activeMakerspace.enabled_modules, "printing")}
          reportsEnabled={moduleEnabled(activeMakerspace.enabled_modules, "reports")}
          guestOnly={guestOnly}
          makerspaceSlug={activeMakerspace.slug}
          singleTenantLocked={singleTenantLocked}
          delegatedRecipientRulesEnabled={
            isMachineOnly &&
            moduleEnabled(activeMakerspace.enabled_modules, "notifications") &&
            featureEnabled(
              activeMakerspace.enabled_features ?? [],
              "notifications.delegated_recipients",
            )
          }
        />
      ) : null}
      {activeTab === "events" && canManageEvents ? <EventsPanel key={makerspaceKey} makerspaceId={activeMakerspace.id} /> : null}
      {activeTab === "bookings" && canManageBookings ? <BookingsPanel key={makerspaceKey} makerspaceId={activeMakerspace.id} /> : null}
      {activeTab === "members" && canManageMakerspace ? (
        <MembersPanel
          key={makerspaceKey}
          makerspaceId={activeMakerspace.id}
          membershipEnabled={moduleEnabled(activeMakerspace.enabled_modules, "membership")}
          actorActions={currentUser.makerspaces.find((item) => item.id === activeMakerspace.id)?.actions ?? []}
          isSuperadmin={isSuperadmin}
        />
      ) : null}
      {activeTab === "payments" && canManageMakerspace ? <PaymentsPanel key={makerspaceKey} makerspaceId={activeMakerspace.id} /> : null}
      {activeTab === "tobuy" ? (
        <ProcurementPanel
          key={makerspaceKey}
          makerspace={activeMakerspace}
          canChooseKind={canChooseToBuyKind}
        />
      ) : null}
      {activeTab === "transfers" && (canEditInventory || isSuperadmin) ? (
        <StockTransferPanel
          key={makerspaceKey}
          makerspace={activeMakerspace}
          makerspaces={makerspaces}
          isSuperadmin={isSuperadmin}
          canEditInventory={canEditInventory}
        />
      ) : null}
      {activeTab === "stocktake" && canEditInventory ? <StocktakePanel key={makerspaceKey} makerspace={activeMakerspace} /> : null}
      {activeTab === "containers" && canManageQr ? <ContainersPanel key={makerspaceKey} makerspace={activeMakerspace} canEditInventory={canEditInventory} /> : null}
      {activeTab === "ledger" ? (
        <Ledger
          key={makerspaceKey}
          makerspace={activeMakerspace}
          isSuperadmin={isSuperadmin}
        />
      ) : null}
      {activeTab === "warranty" && (canEditInventory || canSeePrinting) ? (
        <WarrantyPanel
          key={makerspaceKey}
          makerspace={activeMakerspace}
          canEditInventory={canEditInventory}
        />
      ) : null}
      {activeTab === "accountability" && canViewAudit ? (
        <AccountabilityPanel key={makerspaceKey} makerspace={activeMakerspace} isSuperadmin={isSuperadmin} />
      ) : null}
      {activeTab === "reports" ? (
        <OperationsReports
          key={makerspaceKey}
          makerspace={activeMakerspace}
          makerspaces={makerspaces}
          isSuperadmin={isSuperadmin}
          printingOnly={printingOnly}
          canViewAudit={canViewAudit}
          canManageMachines={canManageMachines}
          canManageMakerspace={canManageMakerspace}
          singleTenantLocked={singleTenantLocked}
        />
      ) : null}
      {activeTab === "direct" && canIssueDirectLoan ? <DirectLoans key={makerspaceKey} makerspace={activeMakerspace} /> : null}
      {activeTab === "handover" && canCollectServiceRequests ? (
        <HandoverConsole key={makerspaceKey} makerspaceId={makerspaceKey} enabled />
      ) : null}
      {activeTab === "bulk" && canEditInventory ? <BulkImport key={makerspaceKey} makerspace={activeMakerspace} /> : null}
      {activeTab === "qr" && canManageQr ? <QrTools key={makerspaceKey} makerspace={activeMakerspace} /> : null}
      {activeTab === "scanner" && canManageQr ? (
        <ScannerPanel
          key={makerspaceKey}
          makerspace={activeMakerspace}
          isSuperadmin={isSuperadmin}
          makerspaces={makerspaces}
        />
      ) : null}
      {activeTab === "api" ? (
        <ApiClientsPanel
          key={makerspaceKey}
          makerspace={activeMakerspace}
          isSuperadmin={isSuperadmin}
          canManageMakerspace={canManageMakerspace}
        />
      ) : null}
      {activeTab === "settings" ? (
        <MakerspaceSettingsPanel
          key={makerspaceKey}
          makerspace={activeMakerspace}
          isSuperadmin={isSuperadmin}
          canManageMakerspace={canManageMakerspace}
          singleTenantLocked={singleTenantLocked}
        />
      ) : null}
      {activeTab === "emailtemplates" ? (
        <EmailTemplatesPanel key={makerspaceKey} makerspace={activeMakerspace} />
      ) : null}
      {activeTab === "email-logs" && canManageMakerspace ? (
        <EmailLogPanel key={makerspaceKey} makerspace={activeMakerspace} />
      ) : null}
      {activeTab === "modules" && isSuperadmin ? (
        <ModulesPanel key={makerspaceKey} makerspaceId={activeMakerspace.id} makerspaceSlug={activeMakerspace.slug} />
      ) : null}
      {activeTab === "platform" ? (
        <Panel title="Platform settings" description="Email delivery, sign-in providers and payouts shared by every makerspace on this deployment.">
          <div className="grid min-w-0 gap-6">
            <PlatformEmailPanel />
            <PlatformSocialAuthPanel />
            {activeMakerspace.platform_hosting ? <PlatformStripeConnectPanel /> : null}
          </div>
        </Panel>
      ) : null}
      {activeTab === "users" && canManageMakerspace ? (
        <Users makerspaces={makerspaces} isSuperadmin={isSuperadmin} currentUser={currentUser} onAuthRefresh={onAuthRefresh} />
      ) : null}
      {activeTab === "exports" && canManageMakerspace ? (
        <DataExportsPanel key={makerspaceKey} makerspaceId={makerspaceKey} />
      ) : null}
      {activeTab === "backups" && canManageMakerspace ? (
        <BackupRestorePanel key={makerspaceKey} makerspaceId={makerspaceKey} isSuperadmin={isSuperadmin} singleTenantLocked={singleTenantLocked} />
      ) : null}
      {activeTab === "migration" && isSuperadmin && !singleTenantLocked ? (
        <TenantMigrationPanel key={makerspaceKey} makerspace={activeMakerspace} />
      ) : null}
      {activeTab === "audit" && canViewAudit ? <AuditLog /> : null}
      </Suspense>
    </StaffPanelErrorBoundary>
  );
}
